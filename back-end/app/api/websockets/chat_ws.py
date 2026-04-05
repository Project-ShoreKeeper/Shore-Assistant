"""
/ws/chat WebSocket endpoint.
Handles the full pipeline: audio/text input -> STT -> Agent -> LLM streaming -> (TTS).
"""

import asyncio
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.stt_service import stt_service
from app.services.agent_service import agent_service
from app.services.tts_service import tts_service
from app.core.config import settings
import numpy as np
import json
import time

router = APIRouter()

SAMPLE_RATE = 16000


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
    print("[Chat WS] Client connected")

    # Per-connection state
    conversation_history: list[dict] = []
    session_config = {
        "language": "en",
        "tts_enabled": True,
    }
    is_cancelled = False

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

    def sanitize_for_tts(text: str) -> str:
        """Strip content that edge-tts cannot synthesize."""
        # Remove tool call blocks
        text = re.sub(r"```tool\s*\n?.*?\n?```", "", text, flags=re.DOTALL)
        # Remove code blocks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        # Remove markdown bold/italic markers
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        # Remove markdown links [text](url)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
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

        # Add user message to conversation history
        conversation_history.append({"role": "user", "content": user_text})

        # Set up TTS sentence queue if TTS is enabled
        tts_enabled = session_config.get("tts_enabled", True)
        sentence_queue: asyncio.Queue = asyncio.Queue()
        tts_task = None

        if tts_enabled:
            tts_task = asyncio.create_task(tts_worker(sentence_queue))

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

                # Feed completed sentences to TTS (skip unspeakable content)
                if tts_enabled and event.get("type") == "llm_sentence":
                    clean = sanitize_for_tts(event["text"])
                    if clean:
                        await sentence_queue.put(clean)

                # When LLM completes, save to conversation history
                if event.get("type") == "llm_complete":
                    conversation_history.append({
                        "role": "assistant",
                        "content": event["text"],
                    })

                    # Keep history manageable (last 20 exchanges)
                    if len(conversation_history) > 40:
                        conversation_history[:] = conversation_history[-40:]

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

                    else:
                        print(f"[Chat WS] Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    await send_json_safe({
                        "type": "error",
                        "message": "Invalid JSON format",
                    })

            # ─── Binary messages (Audio from VAD) ───
            elif "bytes" in message:
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
