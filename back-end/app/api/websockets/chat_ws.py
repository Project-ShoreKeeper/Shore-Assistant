"""
/ws/chat WebSocket endpoint.
Handles the full pipeline: audio/text input -> STT -> Agent -> LLM streaming -> (TTS).
"""

import asyncio
import re
import uuid
import base64 as _b64

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.api.deps import _bearer_token, get_session_store
from app.core.auth import current_user_id, current_user_role
from app.services.ai_client.stt import SttUnavailable, stt_client
from app.services.agent_service import agent_service
from app.services.ai_client.tts import tts_client
from app.services.memory import memory_facade, worker_service
from app.services.image_store import image_store
from app.services.connection_manager import connection_manager
from app.services.notification_service import notification_service
from app.services.copilot_service import copilot_service, summarize_copilot_run
from app.services.computer_use_service import computer_use_service
from app.tools.computer_use_tools import set_session_hooks as _cu_set_hooks, clear_session_hooks as _cu_clear_hooks
from app.core.config import settings
import numpy as np
import json
import time

_ALLOWED_IMAGE_MIME_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,")


def _validate_screenshot_data_url(
    data_url: str | None,
    error: str | None,
) -> tuple[str | None, str | None]:
    """Apply the shared MIME and size gate to a client screenshot."""
    if data_url and not error:
        if not _ALLOWED_IMAGE_MIME_RE.match(data_url):
            return None, "Unsupported screenshot format."
        try:
            payload = data_url.split(",", 1)[1]
            size = len(_b64.b64decode(payload, validate=False))
        except Exception:
            return None, "Malformed screenshot data."
        if size > settings.MAX_IMAGE_BYTES:
            return None, "Screenshot too large."
    return data_url, error


def _validate_images(images) -> str | None:
    """Return None if images is acceptable, else an error string for the client."""
    if not settings.MULTIMODAL_ENABLED:
        return "Vision is not enabled on this server."
    if not isinstance(images, list):
        return "Invalid images payload."
    if len(images) > settings.MAX_IMAGES_PER_MESSAGE:
        return f"Too many images (max {settings.MAX_IMAGES_PER_MESSAGE})."
    for img in images:
        url = img.get("data_url") if isinstance(img, dict) else None
        if not url or not _ALLOWED_IMAGE_MIME_RE.match(url):
            return "Unsupported image format (allowed: png, jpeg, webp)."
        try:
            payload = url.split(",", 1)[1]
            size = len(_b64.b64decode(payload, validate=False))
        except Exception:
            return "Malformed image data."
        if size > settings.MAX_IMAGE_BYTES:
            return "Image too large."
    return None


def _build_memory_message(user_text: str, images: list[dict]) -> dict:
    """Text-only user message that goes on conversation_history / short-term memory."""
    parts = []
    if user_text and user_text.strip():
        parts.append(user_text.strip())
    if images:
        dims = ", ".join(f"{i['width']}x{i['height']}" for i in images)
        parts.append(f"[Attached {len(images)} image(s): {dims}]")
    return {"role": "user", "content": "\n\n".join(parts) if parts else ""}


def _build_live_message(user_text: str, images: list[dict]) -> dict:
    """OpenAI multimodal content array — the version llama-server sees this turn only."""
    text_part = user_text if (user_text and user_text.strip()) else " "
    content = [{"type": "text", "text": text_part}]
    for img in images:
        content.append({"type": "image_url",
                        "image_url": {"url": img["data_url"]}})
    return {"role": "user", "content": content}


def _make_computer_use_emitter(send_json_threadsafe, session_id: str):
    """Build the emit(msg) callback the computer-use loop pushes steps through.

    The loop calls emit() synchronously. send_json_threadsafe may return a
    coroutine (production `send_json_safe`) or None (a sync test fake); we
    schedule it only when awaitable so both work. When COMPUTER_USE_DEBUG_DIR
    is set, computer_use_step messages also persist their SoM JPEG + decision
    JSON for post-hoc E2E debugging.
    """
    import asyncio
    import inspect
    import base64 as _b
    from pathlib import Path

    def emit(msg: dict):
        result = send_json_threadsafe(msg)
        if inspect.isawaitable(result):
            asyncio.get_event_loop().create_task(result)

        debug_dir = settings.COMPUTER_USE_DEBUG_DIR
        if debug_dir and msg.get("type") == "computer_use_step":
            try:
                sdir = Path(debug_dir) / session_id
                sdir.mkdir(parents=True, exist_ok=True)
                step = msg.get("step", 0)
                som = msg.get("som_image", "")
                if som.startswith("data:image"):
                    b64 = som.split(",", 1)[1]
                    (sdir / f"step_{step}.jpg").write_bytes(_b.b64decode(b64))
                (sdir / f"step_{step}.json").write_text(
                    json.dumps({k: v for k, v in msg.items() if k != "som_image"}),
                    encoding="utf-8",
                )
            except Exception:
                pass

    return emit


router = APIRouter()

SAMPLE_RATE = 16000


def _websocket_session_id(
    websocket: WebSocket,
) -> tuple[str | None, str | None]:
    """Read Bearer auth from the upgrade or browser WS subprotocol.

    Browsers do not expose custom WebSocket headers, so the desktop
    frontend sends protocols ``["bearer", "<token>"]``. Non-browser
    clients may use the standard Authorization header. Cookie fallback
    keeps the hosted web app compatible.
    """
    sid = _bearer_token(websocket.headers.get("Authorization"))
    if sid is not None:
        return sid, None

    protocols = [
        value.strip()
        for value in websocket.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if value.strip()
    ]
    if len(protocols) >= 2 and protocols[0].lower() == "bearer":
        return protocols[1], "bearer"

    return websocket.cookies.get(settings.AUTH_COOKIE_NAME), None


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
    # Authenticate at upgrade. When AUTH_ENABLED=False, deps treat the
    # connection as the legacy admin user.
    accepted_subprotocol = None
    if settings.AUTH_ENABLED:
        sid, accepted_subprotocol = _websocket_session_id(websocket)
        session = await get_session_store().read(sid) if sid else None
        if session is None:
            # 4401 = our custom "unauthenticated" close code — frontend
            # stops its reconnect loop on this.
            await websocket.close(code=4401, reason="unauthenticated")
            return
        ws_user_id = session.user.id
        ws_user_role = session.user.role
    else:
        ws_user_id = "legacy"
        ws_user_role = "admin"

    # Make the active user visible to tool calls (clear_memory etc) that
    # run in this WS's asyncio task.
    current_user_id.set(ws_user_id)
    current_user_role.set(ws_user_role)

    await websocket.accept(subprotocol=accepted_subprotocol)

    # Per-connection state
    session_id = str(uuid.uuid4())[:8]
    screen_access_active = False


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
    my_send_json = send_json_safe  # Track our own ref for cleanup guard

    from app.services.terminal_service import terminal_service
    terminal_service.broadcast = send_json_safe

    # Load persisted history. The frontend rehydration code expects
    # assistant metadata (thinking_text, agent_actions, ...) at the top
    # level of each message dict, not nested under `extras` the way the
    # Redis `Message` schema stores them. Flatten on the way out so the
    # wire protocol stays stable; storage remains nested.
    persisted_msgs = await memory_facade.short_term.load(user_id=ws_user_id) if memory_facade.short_term else []
    persisted: list[dict] = []
    for m in persisted_msgs:
        out = {"role": m.role, "content": m.content, "timestamp": m.timestamp}
        if m.extras:
            out.update(m.extras)
        persisted.append(out)
    conversation_history: list[dict] = [
        {"role": m["role"], "content": m["content"]} for m in persisted
    ]

    # Push history snapshot to client so the UI can rehydrate
    await send_json_safe({"type": "history", "messages": persisted})


    session_config = {
        "language": "en",
        "tts_enabled": True,
        "thinking": False,
    }
    is_cancelled = False

    def sanitize_for_tts(text: str) -> str:
        """Strip content that TTS cannot synthesize."""
        # Remove any code blocks (```anything```)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        # Remove partial/unclosed code blocks
        text = re.sub(r"```.*", "", text, flags=re.DOTALL)
        # Remove block math ($$...$$)
        text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
        # Remove inline math ($...$)
        text = re.sub(r"\$[^$]+?\$", "", text)
        # Remove raw JSON fragments
        text = re.sub(r"\{.*?\}", "", text, flags=re.DOTALL)
        # Remove URLs (with and without protocol)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"www\.\S+", "", text)
        # Remove dangling link lead-ins left after URL removal (e.g. "The link is:")
        text = re.sub(r"(?:the\s+)?(?:download\s+)?(?:link|url)\s*(?:is|here)\s*:?\s*$", "", text, flags=re.IGNORECASE)
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
        started = False
        voice_map = {"en": "af_heart", "ja": "jf_alpha", "zh": "zf_xiaobei"}
        tts_sample_rate = 24000

        while True:
            sentence = await sentence_queue.get()
            if sentence is None:
                break

            try:
                async with notification_service.tts_lock:
                    language = session_config.get("language", "en")
                    voice = voice_map.get(language, "af_heart")

                    # Send tts_start only once for the entire response
                    if not started:
                        await send_json_safe({
                            "type": "tts_start",
                            "sample_rate": tts_sample_rate,
                            "format": "pcm_s16le",
                        })
                        started = True

                    async for chunk in tts_client.stream_pcm(
                        text=sentence,
                        voice=voice,
                        language=language,
                    ):
                        await send_binary_safe(chunk)

            except Exception:
                pass

        # Send tts_end once after all sentences are done
        if started:
            await send_json_safe({"type": "tts_end"})

    async def run_agent_pipeline(
        user_text: str,
        source: str = "keyboard",
        task_id: str | None = None,
        images: list[dict] | None = None,
    ):
        """Run the full agent pipeline and stream results to the client."""
        nonlocal is_cancelled

        is_notification = source == "notification"

        # Build the text-only "memory" form of the user turn (image bytes never
        # land on disk or in conversation_history), and the multimodal "live"
        # form that llama-server sees just this turn.
        if not is_notification:
            # Persist the raw image bytes (disk + Postgres metadata row) so
            # the user can view them again later — separate from the text
            # placeholder below, which is all the agent/memory layers see.
            saved_images = (
                await image_store.save_attachments(images, user_id=ws_user_id, role="user")
                if images else []
            )
            memory_message = _build_memory_message(user_text, images or [])
            conversation_history.append(memory_message)
            await memory_facade.append_user(
                content=memory_message["content"],
                user_id=ws_user_id,
                extras={"images": saved_images} if saved_images else None,
            )
        live_user_message = (
            _build_live_message(user_text, images) if images else None
        )

        # Accumulate metadata for persistence alongside the assistant response
        current_thinking: str = ""
        current_actions: list[dict] = []

        # Set up TTS sentence queue if TTS is enabled
        tts_enabled = session_config.get("tts_enabled", True)
        sentence_queue: asyncio.Queue = asyncio.Queue()
        tts_task = None

        if tts_enabled:
            tts_task = asyncio.create_task(tts_worker(sentence_queue))

        # Per-turn memory: pull Profile + Episodic in parallel with Redis.
        # bundle.short_term is intentionally unused — the local
        # conversation_history list above is the source of truth for the LLM
        # because it already reflects the in-progress append.
        # Notifications skip this entirely to avoid the Postgres+Qdrant
        # round-trip; agent_service.run would drop the bundle anyway.
        bundle = (
            await memory_facade.assemble_context(user_text, user_id=ws_user_id)
            if not is_notification else None
        )

        try:
            async for event in agent_service.run(
                user_text, conversation_history,
                memory_bundle=bundle,
                thinking=session_config.get("thinking", False),
                no_tools=is_notification,
                live_user_message=live_user_message,
            ):
                if is_cancelled:
                    is_cancelled = False
                    await send_json_safe({
                        "type": "status",
                        "message": "Generation cancelled",
                    })
                    return

                await send_json_safe(event)

                # Collect tool call metadata
                if event.get("type") == "agent_action":
                    if event.get("action") == "tool_call":
                        current_actions.append({
                            "action": "tool_call",
                            "tool": event.get("tool"),
                            "args": event.get("args"),
                            "result": None,
                            "status": "running",
                            "timestamp": event.get("timestamp", time.time()),
                        })
                    elif event.get("action") == "tool_result":
                        # Update the most recent running action for this tool
                        for action in reversed(current_actions):
                            if (
                                action.get("tool") == event.get("tool")
                                and action.get("status") == "running"
                            ):
                                action["result"] = event.get("result")
                                action["status"] = event.get("status", "completed")
                                break

                # Collect final thinking text
                if event.get("type") == "llm_thinking_done":
                    current_thinking = event.get("text", "")

                # Feed completed sentences to TTS
                if tts_enabled and event.get("type") == "llm_sentence":
                    clean = sanitize_for_tts(event["text"])
                    if clean:
                        await sentence_queue.put(clean)

                # When LLM completes, save to conversation history and persist
                if event.get("type") == "llm_complete":
                    assistant_text = event["text"]

                    # Don't save empty responses to history/memory
                    if assistant_text.strip():
                        conversation_history.append({
                            "role": "assistant",
                            "content": assistant_text,
                        })
                        extras = {
                            "thinking_text": current_thinking or None,
                            "agent_actions": current_actions or None,
                            "is_notification": is_notification,
                            "task_id": task_id,
                        }
                        await memory_facade.append_assistant(
                            content=assistant_text,
                            user_id=ws_user_id,
                            extras=extras,
                        )
                        # Phase 3: trigger LOCOMO worker debounce only for the
                        # admin user (Luna). Other allowlisted users can chat
                        # but their words must not be extracted into Luna's
                        # shared Profile / Episodic memory.
                        if not is_notification and ws_user_role == "admin":
                            try:
                                await worker_service.on_turn_completed(
                                    user_id=ws_user_id,
                                )
                            except Exception as e:
                                print(f"[chat_ws] worker.on_turn_completed failed: {e!r}")

                    # Keep in-memory history manageable
                    max_messages = settings.MEMORY_MAX_TURNS * 2
                    if len(conversation_history) > max_messages:
                        conversation_history[:] = conversation_history[-max_messages:]

        except Exception as e:
            await send_json_safe({
                "type": "error",
                "message": f"Agent error: {str(e)}",
            })
        finally:
            # Signal TTS worker to stop
            if tts_task:
                await sentence_queue.put(None)
                await tts_task

    # Active agent task — keep a handle so we can cancel on disconnect and so
    # we never await it inline (otherwise the WS receive loop deadlocks: the
    # agent is waiting for control messages — terminal_confirm_response — that
    # we can only deliver from this very loop).
    agent_task: asyncio.Task | None = None

    async def _start_agent(
        user_text: str,
        source: str = "keyboard",
        task_id: str | None = None,
        images: list[dict] | None = None,
    ):
        nonlocal agent_task
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass
        agent_task = asyncio.create_task(
            run_agent_pipeline(user_text, source, task_id=task_id, images=images)
        )

    # Register agent callback for proactive notifications
    async def run_notification(prompt: str, task_id: str | None = None):
        """Run a notification prompt through the full agent pipeline."""
        await _start_agent(prompt, source="notification", task_id=task_id)

    notification_service.set_agent_callback(run_notification)

    async def run_copilot_pipeline(framing: str, screenshot: dict):
        """Run one co-pilot turn: feed the screenshot to the agent with tools,
        buffer the output, and emit a single copilot_message (or stay silent on
        __NOOP__). Ephemeral: the framing/screenshot never touch history/memory.
        Confirm dialogs for risky commands are broadcast live by terminal_service.
        """
        # Transient history: prior turns + the framing as the current user turn.
        # agent_service.run builds its own message list, so the real
        # conversation_history is never mutated.
        temp_history = list(conversation_history) + [
            {"role": "user", "content": framing}
        ]
        live_msg = _build_live_message(framing, [screenshot])

        events: list[dict] = []
        try:
            async for event in agent_service.run(
                framing, temp_history,
                memory_bundle=None,
                thinking=False,
                no_tools=False,
                live_user_message=live_msg,
            ):
                events.append(event)
        except Exception as e:
            print(f"[Copilot] pipeline error: {e!r}")
            return

        result = summarize_copilot_run(events)
        if result is None:
            return  # __NOOP__ / nothing useful — stay silent

        await send_json_safe({
            "type": "copilot_message",
            "text": result["text"],
            "agent_actions": result["agent_actions"],
            "timestamp": time.time(),
        })

        if result["text"].strip():
            conversation_history.append(
                {"role": "assistant", "content": result["text"]}
            )
            await memory_facade.append_assistant(
                content=result["text"],
                user_id=ws_user_id,
                extras={
                    "is_copilot": True,
                    "agent_actions": result["agent_actions"] or None,
                },
            )

    async def _start_copilot(framing: str, screenshot: dict):
        nonlocal agent_task
        if agent_task and not agent_task.done():
            return  # busy — a user/copilot turn is already running; skip
        agent_task = asyncio.create_task(
            run_copilot_pipeline(framing, screenshot)
        )

    copilot_service.attach(
        trigger_cb=_start_copilot,
        is_busy_cb=lambda: bool(agent_task and not agent_task.done()),
    )

    _cu_emit = _make_computer_use_emitter(send_json_safe, session_id)
    _cu_set_hooks(_cu_emit, is_admin=(ws_user_role == "admin"))
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
                        images = data.get("images") or []
                        if images:
                            err = _validate_images(images)
                            if err:
                                await send_json_safe({"type": "status", "message": err})
                                continue
                        if user_text or images:
                            await _start_agent(user_text, source, images=images)

                    elif msg_type == "config":
                        config_data = data.get("data", {})
                        session_config.update(config_data)

                        await send_json_safe({
                            "type": "status",
                            "message": f"Config updated: {session_config}",
                        })

                    elif msg_type == "cancel":
                        is_cancelled = True
                        if agent_task and not agent_task.done():
                            agent_task.cancel()

                    elif msg_type == "copilot_start":
                        started = await copilot_service.start_session()
                        await send_json_safe({
                            "type": "copilot_state",
                            "active": started,
                        })

                    elif msg_type == "copilot_stop":
                        await copilot_service.stop_session()
                        await send_json_safe({
                            "type": "copilot_state",
                            "active": False,
                        })

                    elif msg_type == "computer_use_stop":
                        computer_use_service.stop()
                        await send_json_safe({
                            "type": "computer_use_state",
                            "status": "stopped",
                            "goal": "",
                            "steps_taken": 0,
                        })

                    elif msg_type == "clear_memory":
                        conversation_history.clear()
                        await memory_facade.clear(user_id=ws_user_id)

                        await send_json_safe({
                            "type": "status",
                            "message": "Memory cleared",
                        })

                    elif msg_type == "terminal_confirm_response":
                        import sys
                        sys.stderr.write(f"[chat_ws] terminal_confirm_response received: {data}\n")
                        sys.stderr.flush()
                        terminal_service.resolve_confirm(
                            data["request_id"], data["decision"]
                        )

                    elif msg_type == "terminal_user_input":
                        name_lookup = next(
                            (n for n, s in terminal_service.sessions.items()
                             if s["session_id"] == data["session_id"]),
                            None,
                        )
                        if name_lookup:
                            await terminal_service.send_to_session(
                                name_lookup, data["data"], wait_seconds=0
                            )

                    elif msg_type == "terminal_resize":
                        entry = next(
                            (s for s in terminal_service.sessions.values()
                             if s["session_id"] == data["session_id"]),
                            None,
                        )
                        if entry:
                            await terminal_service.backend.resize_session_exec(
                                entry["session_id"], data["cols"], data["rows"]
                            )

                    elif msg_type == "terminal_close_session":
                        name_lookup = next(
                            (n for n, s in terminal_service.sessions.items()
                             if s["session_id"] == data["session_id"]),
                            None,
                        )
                        if name_lookup:
                            await terminal_service.close_session(name_lookup)

                    elif msg_type == "terminal_resync":
                        sessions_list = terminal_service.list_sessions()
                        for s in sessions_list:
                            entry = next(
                                (v for v in terminal_service.sessions.values()
                                 if v["session_id"] == s["session_id"]),
                                None,
                            )
                            s["buffer"] = entry.get("_buffer_tail", "") if entry else ""

                        await send_json_safe({
                            "type": "terminal_sessions_snapshot",
                            "sessions": sessions_list,
                        })

                    else:
                        pass

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
                    stt_result = await stt_client.transcribe(
                        audio=audio_float32,
                        language=session_config.get("language", "en"),
                    )
                except SttUnavailable:
                    await send_json_safe({
                        "type": "transcript",
                        "text": "",
                        "isFinal": True,
                        "data": {"skipped": True, "reason": "stt_unavailable"},
                    })
                    continue
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
                    await _start_agent(transcript_text, source="voice")

    except WebSocketDisconnect:
        pass
    except RuntimeError as e:
        if "disconnect" not in str(e).lower():
            raise
    except Exception as e:
        await send_json_safe({
            "type": "error",
            "message": f"Server error: {str(e)}",
        })
    finally:
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass
        copilot_service.detach()
        computer_use_service.stop()
        _cu_clear_hooks()
        # Only unregister if we're still the active connection
        if connection_manager._send_json is my_send_json:
            notification_service.clear_agent_callback()
            connection_manager.unregister()
            terminal_service.broadcast = None
