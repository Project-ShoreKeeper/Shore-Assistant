from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.services.stt_service import stt_service
import numpy as np
import json
import time

app = FastAPI(title="Shore STT API", description="Backend cho module Speech-To-Text", version="1.0.0")


@app.on_event("startup")
def startup_load_model():
    """
    Load mô hình Whisper 1 lần duy nhất khi server khởi động.
    Model sẽ được cache trong RAM và tái sử dụng cho mọi request.
    """
    stt_service.load_model()

# Cấu hình CORS để frontend React có thể gọi API mà không bị lỗi
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Nên giới hạn domain trong môi trường production (ví dụ: ["http://localhost:5173"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cấu hình audio mặc định (phải khớp với frontend STTConfig)
SAMPLE_RATE = 16000  # Hz - khớp với frontend audio.sampleRate
CHANNELS = 1         # Mono - khớp với frontend audio.channels


@app.get("/")
def read_root():
    return {"message": "Welcome to Shore STT FastAPI Backend"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "STT Backend is running"}


# ==================== WebSocket STT (VAD-based) ====================

@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket):
    """
    WebSocket endpoint nhận đoạn audio hoàn chỉnh từ frontend (VAD-based).

    Flow:
      1. Frontend kết nối tới ws://localhost:8000/ws/audio
      2. Frontend có thể gửi JSON (config/control) hoặc Binary (audio)
      3. Khi VAD phát hiện người dùng nói xong → Frontend gửi toàn bộ
         đoạn audio dạng Float32 PCM (16kHz, Mono)
      4. Backend chuyển đổi → chạy STT (Whisper) → trả kết quả JSON

    Response format (khớp với STTMessageEvent ở frontend):
      { type: "transcript", text: "...", isFinal: true }
      { type: "status",     message: "..." }
      { type: "error",      message: "..." }
    """
    await websocket.accept()
    print("[WS] Client đã kết nối")

    # Cấu hình session (có thể được frontend ghi đè qua message type "config")
    session_config = {
        "language": "en",
        "sample_rate": SAMPLE_RATE,
    }

    try:
        while True:
            # WebSocket có thể nhận cả Text (JSON) và Binary (audio)
            message = await websocket.receive()

            # ─── Xử lý tin nhắn dạng Text (JSON) ───
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "")

                    if msg_type == "config":
                        # Frontend gửi cấu hình session (ngôn ngữ, sample rate, model_size, ...)
                        config_data = data.get("data", {})
                        
                        # Xử lý đổi model nếu có yêu cầu
                        requested_model = config_data.get("model_size")
                        if requested_model:
                            print(f"[WS] Yêu cầu chuyển model sang: {requested_model}")
                            await websocket.send_json({
                                "type": "status",
                                "message": f"Switching model to {requested_model}..."
                            })
                            stt_service.load_model(requested_model)

                        session_config.update(config_data)
                        print(f"[WS] Cập nhật config: {session_config}")
                        await websocket.send_json({
                            "type": "status",
                            "message": f"Config updated: {session_config}"
                        })
                    else:
                        print(f"[WS] Nhận text message không xác định: {data}")

                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON format"
                    })

            # ─── Xử lý tin nhắn dạng Binary (Audio từ VAD) ───
            elif "bytes" in message:
                audio_bytes = message["bytes"]
                start_time = time.time()

                # Chuyển đổi bytes → numpy Float32 array
                # Frontend gửi Float32Array.buffer → mỗi sample = 4 bytes
                audio_float32 = np.frombuffer(audio_bytes, dtype=np.float32)

                duration_sec = len(audio_float32) / SAMPLE_RATE
                print(f"[WS] Nhận đoạn audio: {len(audio_float32)} samples "
                      f"({duration_sec:.2f}s)")

                # Kiểm tra dữ liệu hợp lệ
                if len(audio_float32) == 0:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty audio segment received"
                    })
                    continue

                # Kiểm tra audio không phải toàn silence (noise floor)
                audio_rms = np.sqrt(np.mean(audio_float32 ** 2))
                if audio_rms < 0.001:
                    print(f"[WS] Audio quá nhỏ (RMS={audio_rms:.6f}), bỏ qua")
                    await websocket.send_json({
                        "type": "transcript",
                        "text": "",
                        "isFinal": True,
                        "data": {"skipped": True, "reason": "silence"}
                    })
                    continue

                # ─── Gọi Faster-Whisper STT ───
                stt_result = await stt_service.transcribe_async(
                    audio=audio_float32,
                    language=session_config.get("language", "en"),
                )
                transcript_text = stt_result["text"]
                detected_language = stt_result["language"]
                language_prob = stt_result["language_prob"]
                segments = stt_result["segments"]

                processing_time = time.time() - start_time

                # Gửi kết quả về frontend (khớp STTMessageEvent format)
                await websocket.send_json({
                    "type": "transcript",
                    "text": transcript_text,
                    "isFinal": True,
                    "data": {
                        "duration": round(duration_sec, 2),
                        "processing_time": round(processing_time, 3),
                        "language": detected_language,
                        "language_prob": language_prob,
                        "segments": segments,
                    }
                })

    except WebSocketDisconnect:
        print("[WS] Client đã ngắt kết nối")
    except RuntimeError as e:
        # Starlette raises RuntimeError (not WebSocketDisconnect) when
        # receive() is called after a disconnect message was already processed.
        if "disconnect" in str(e).lower():
            print("[WS] Client đã ngắt kết nối")
        else:
            print(f"[WS] Lỗi không mong muốn: {e}")
    except Exception as e:
        print(f"[WS] Lỗi không mong muốn: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Server error: {str(e)}"
            })
        except Exception:
            pass
