"""
/ws/chat WebSocket endpoint.
Handles the full pipeline: audio/text input -> STT -> Agent -> LLM streaming -> (TTS).
"""

import asyncio
import re
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.stt_service import stt_service
from app.services.agent_service import agent_service
from app.services.tts_service import tts_service
from app.services.memory_service import memory_service
from app.services.connection_manager import connection_manager
from app.services.notification_service import notification_service
from app.core.config import settings
import numpy as np
import json
import time

router = APIRouter()

SAMPLE_RATE = 16000

# Friendly spoken names for tools (used by TTS instead of raw tool names)
_TOOL_SPOKEN_NAMES = {
    "get_system_time": "the clock",
    "read_file": "the file reader",
    "list_directory": "the directory listing",
    "clear_memory": "memory clear",
    "search_web": "web search",
    "web_scrape": "the web scraper",
    "capture_screen": "screen capture",
    "analyze_screen": "screen analysis",
    "set_reminder": "the reminder system",
    "set_scheduled_task": "the scheduler",
    "cancel_task": "task cancellation",
    "list_tasks": "the task list",
}


def _tool_spoken_name(tool_name: str) -> str:
    return _TOOL_SPOKEN_NAMES.get(tool_name, tool_name.replace("_", " "))


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Unified chat WebSocket endpoint.

    Client -> Server:
      - JSON: {"type": "user_message", "text": "...", "source": "voice"|"keyboard"}
      - JSON: {"type": "config", "data": {...}}
      - JSON: {"type": "cancel"}
      - Binary: Float32Array buffer (from VAD, triggers STT -> Agent)

    Server -> Client:
      - {"type": "transcript", ...}       -- STT result
      - {"type": "agent_action", ...}     -- Agent status updates
      - {"type": "llm_token", ...}        -- Streamed LLM tokens
      - {"type": "llm_sentence", ...}     -- Complete sentence (for TTS)
      - {"type": "llm_complete", ...}     -- Final response
      - {"type": "status"|"error", ...}   -- Status/error messages
    """
    await websocket.accept()

    # Per-connection state
    session_id = str(uuid.uuid4())[:8]
    print(f"[Chat WS] Client connected (session: {session_id})")

    # Register send functions for proactive notifications
    async def send_json_safe(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    async def send_binary_safe(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    connection_manager.register(send_json_safe, send_binary_safe)

    # Load persisted history
    persisted = memory_service.load(session_id="default")
    conversation_history: list[dict] = [
        {"role": m["role"], "content": m["content"]} for m in persisted
    ]
    if conversation_history:
        print(f"[Chat WS] Loaded {len(conversation_history)} messages from memory")

    session_config = {
        "language": "en",
        "tts_enabled": True,
    }
    is_cancelled = False

    def sanitize_for_tts(text: str) -> str:
        """Strip content that TTS cannot synthesize."""
        # Remove any code blocks (```anything```)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove partial/unclosed code blocks
        text = re.sub(r"```.*", "", text, flags=re.DOTALL)
        # Remove raw JSON fragments
        text = re.sub(r"\{.*?\}", "", text, flags=re.DOTALL)
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        # Remove markdown bold/italic markers
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        # Remove markdown links [text](url)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Replace ellipsis with a comma pause (Kokoro handles commas better)
        text = re.sub(r"\.{2,}", ",", text)
        text = re.sub(r"…", ",", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Remove leading comma/punctuation
        text = re.sub(r"^[,\s]+", "", text)
        return text

    async def tts_worker(sentence_queue: asyncio.Queue):
        """Consume sentences from the queue and stream TTS audio to the client."""
        if not tts_service.is_available:
            while True:
                item = await sentence_queue.get()
                if item is None:
                    break
            return

        started = False

        while True:
            sentence = await sentence_queue.get()
            if sentence is None:
                break

            try:
                async with notification_service.tts_lock:
                    tts_service.set_voice_for_language(
                        session_config.get("language", "en")
                    )

                    # Send tts_start only once for the entire response
                    if not started:
                        await send_json_safe({
                            "type": "tts_start",
                            "sample_rate": tts_service.sample_rate,
                            "format": "pcm_s16le",
                        })
                        started = True

                    async for chunk in tts_service.synthesize_stream_pcm(sentence):
                        await send_binary_safe(chunk)

            except Exception as e:
                print(f"[Chat WS] TTS error: {type(e).__name__}: {e!r}")
                print(f"[Chat WS] TTS failed sentence: {sentence!r}")
                import traceback
                traceback.print_exc()

        # Send tts_end once after all sentences are done
        if started:
            await send_json_safe({"type": "tts_end"})

    async def run_agent_pipeline(user_text: str, source: str = "keyboard"):
        """Run the full agent pipeline and stream results to the client."""
        nonlocal is_cancelled

        is_notification = source == "notification"

        print(f"\n[Chat WS] >>>>>> run_agent_pipeline <<<<<<")
        print(f"[Chat WS] User text: {user_text[:200]}")
        print(f"[Chat WS] Source: {source}")
        print(f"[Chat WS] History length BEFORE append: {len(conversation_history)}")

        # Don't persist notification prompts as user messages
        if not is_notification:
            conversation_history.append({"role": "user", "content": user_text})
            memory_service.append(session_id="default", role="user", content=user_text)
            print(f"[Chat WS] History length AFTER append: {len(conversation_history)}")

        # Set up TTS sentence queue if TTS is enabled
        tts_enabled = session_config.get("tts_enabled", True)
        sentence_queue: asyncio.Queue = asyncio.Queue()
        tts_task = None

        if tts_enabled:
            tts_task = asyncio.create_task(tts_worker(sentence_queue))

        # Track whether current LLM response contains a tool call
        tts_suppressed = False

        try:
            async for event in agent_service.run(user_text, conversation_history):
                if is_cancelled:
                    is_cancelled = False
                    await send_json_safe({
                        "type": "status",
                        "message": "Generation cancelled",
                    })
                    return

                await send_json_safe(event)

                # When a tool call is detected, speak a friendly line
                # instead of the raw JSON block
                if tts_enabled and event.get("type") == "agent_action":
                    if event.get("action") == "tool_call":
                        tool_name = event.get("tool", "a tool")
                        friendly = _tool_spoken_name(tool_name)
                        await sentence_queue.put(f"Let me use {friendly}.")
                        tts_suppressed = False  # Reset for next LLM round

                # Feed completed sentences to TTS (skip tool-call content)
                if tts_enabled and event.get("type") == "llm_sentence":
                    if not tts_suppressed:
                        clean = sanitize_for_tts(event["text"])
                        if clean:
                            # Check if this sentence is starting a tool block
                            if "```" in event["text"] or event["text"].strip().startswith("{") or '"tool"' in event["text"]:
                                tts_suppressed = True
                            else:
                                await sentence_queue.put(clean)

                # Reset suppression when a new LLM round starts
                if event.get("type") == "agent_action" and event.get("action") == "thinking":
                    tts_suppressed = False

                # When LLM completes, save to conversation history and persist
                if event.get("type") == "llm_complete":
                    assistant_text = event["text"]
                    print(f"[Chat WS] LLM complete — response length: {len(assistant_text)}")
                    print(f"[Chat WS] LLM complete — preview: {assistant_text[:200]}")

                    # Don't save empty responses to history/memory
                    if not assistant_text.strip():
                        print(f"[Chat WS] WARNING: Empty response — NOT saving to history")
                    else:
                        conversation_history.append({
                            "role": "assistant",
                            "content": assistant_text,
                        })
                        memory_service.append(
                            session_id="default",
                            role="assistant",
                            content=assistant_text,
                        )
                    print(f"[Chat WS] History length after response: {len(conversation_history)}")

                    # Keep in-memory history manageable
                    max_messages = settings.MEMORY_MAX_TURNS * 2
                    if len(conversation_history) > max_messages:
                        conversation_history[:] = conversation_history[-max_messages:]

        except Exception as e:
            print(f"[Chat WS] Agent error: {e}")
            await send_json_safe({
                "type": "error",
                "message": f"Agent error: {str(e)}",
            })
        finally:
            # Signal TTS worker to stop
            if tts_task:
                await sentence_queue.put(None)
                await tts_task

    # Register agent callback for proactive notifications
    async def run_notification(prompt: str):
        """Run a notification prompt through the full agent pipeline."""
        await run_agent_pipeline(prompt, source="notification")

    notification_service.set_agent_callback(run_notification)

    # Drain any notifications that fired while disconnected
    await notification_service.drain_pending()

    try:
        while True:
            message = await websocket.receive()

            # ─── Text messages (JSON) ───
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "")

                    if msg_type == "user_message":
                        user_text = data.get("text", "").strip()
                        source = data.get("source", "keyboard")
                        if user_text:
                            await run_agent_pipeline(user_text, source)

                    elif msg_type == "config":
                        config_data = data.get("data", {})
                        session_config.update(config_data)
                        print(f"[Chat WS] Config updated: {session_config}")
                        await send_json_safe({
                            "type": "status",
                            "message": f"Config updated: {session_config}",
                        })

                    elif msg_type == "cancel":
                        is_cancelled = True
                        print("[Chat WS] Generation cancel requested")

                    elif msg_type == "clear_memory":
                        conversation_history.clear()
                        memory_service.clear("default")
                        print("[Chat WS] Memory cleared")
                        await send_json_safe({
                            "type": "status",
                            "message": "Memory cleared",
                        })

                    else:
                        print(f"[Chat WS] Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    await send_json_safe({
                        "type": "error",
                        "message": "Invalid JSON format",
                    })

            # ─── Binary messages (Audio from VAD) ───
            elif "bytes" in message:
                if not settings.STT_ENABLED:
                    await send_json_safe({
                        "type": "error",
                        "message": "STT is disabled",
                    })
                    continue

                audio_bytes = message["bytes"]
                start_time = time.time()

                audio_float32 = np.frombuffer(audio_bytes, dtype=np.float32)
                duration_sec = len(audio_float32) / SAMPLE_RATE

                if len(audio_float32) == 0:
                    await send_json_safe({
                        "type": "error",
                        "message": "Empty audio segment",
                    })
                    continue

                # Check for silence
                audio_rms = np.sqrt(np.mean(audio_float32 ** 2))
                if audio_rms < 0.001:
                    await send_json_safe({
                        "type": "transcript",
                        "text": "",
                        "isFinal": True,
                        "data": {"skipped": True, "reason": "silence"},
                    })
                    continue

                # Run STT
                try:
                    stt_result = await stt_service.transcribe_async(
                        audio=audio_float32,
                        language=session_config.get("language", "en"),
                    )
                except Exception as e:
                    await send_json_safe({
                        "type": "error",
                        "message": f"STT error: {str(e)}",
                    })
                    continue

                transcript_text = stt_result["text"].strip()
                processing_time = time.time() - start_time

                # Send transcript to client
                await send_json_safe({
                    "type": "transcript",
                    "text": transcript_text,
                    "isFinal": True,
                    "data": {
                        "duration": round(duration_sec, 2),
                        "processing_time": round(processing_time, 3),
                        "language": stt_result["language"],
                        "language_prob": stt_result["language_prob"],
                        "segments": stt_result["segments"],
                    },
                })

                # Feed transcript to agent (if non-empty)
                if transcript_text:
                    await run_agent_pipeline(transcript_text, source="voice")

    except WebSocketDisconnect:
        print("[Chat WS] Client disconnected")
    except RuntimeError as e:
        if "disconnect" in str(e).lower():
            print("[Chat WS] Client disconnected")
        else:
            print(f"[Chat WS] Unexpected error: {e}")
    except Exception as e:
        print(f"[Chat WS] Unexpected error: {e}")
        await send_json_safe({
            "type": "error",
            "message": f"Server error: {str(e)}",
        })
    finally:
        notification_service.clear_agent_callback()
        connection_manager.unregister()
