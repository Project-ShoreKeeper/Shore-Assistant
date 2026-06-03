# Shore STT Backend

Đây là module Backend sử dụng **FastAPI** phục vụ cho Speech-To-Text processing.

## Prerequisites

Before starting the FastAPI server, run the `shore-pty-service` microservice separately — it is the sole PTY executor backend:

```bash
cd shore-pty-service
npm install
npm run build
npm start          # Starts WS server at ws://127.0.0.1:9100
```

See `shore-pty-service/README.md` for full setup details. For architecture and configuration options, refer to the top-level `CLAUDE.md`.

## Yêu cầu môi trường

- Python 3.9+

## Cài đặt (Mac / Linux)

```bash
# 1. Di chuyển vào folder backend
cd back-end

# 2. Tạo môi trường ảo (Virtual Environment)
python3 -m venv venv

# 3. Kích hoạt môi trường ảo
source venv/bin/activate

# 4. Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

## Chạy Server (Development)

Trong khi vẫn đang kích hoạt môi trường ảo (`venv`), chạy lệnh:

```bash
uvicorn app.main:app --reload
```

Server sẽ khởi động và lắng nghe tại `http://localhost:9000`.

- Giao diện Swagger UI (xem các API): [http://localhost:9000/docs](http://localhost:9000/docs)
- Redoc UI: [http://localhost:9000/redoc](http://localhost:9000/redoc)
