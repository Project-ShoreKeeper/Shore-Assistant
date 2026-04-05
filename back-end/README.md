# Shore STT Backend

Đây là module Backend sử dụng **FastAPI** phục vụ cho Speech-To-Text processing.

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

Server sẽ khởi động và lắng nghe tại `http://localhost:8000`.

- Giao diện Swagger UI (xem các API): [http://localhost:8000/docs](http://localhost:8000/docs)
- Redoc UI: [http://localhost:8000/redoc](http://localhost:8000/redoc)
