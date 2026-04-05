import asyncio
import websockets
import json
import numpy as np

async def test_stt():
    uri = "ws://localhost:8000/ws/audio"
    async with websockets.connect(uri) as websocket:
        print("--- Đã kết nối tới server ---")

        # 1. Gửi cấu hình (Optional)
        config = {"type": "config", "data": {"language": "en"}}
        await websocket.send(json.dumps(config))
        print("Đã gửi config")

        # Nhận phản hồi config từ server (để không bị lẫn với kết quả transcript)
        config_response = await websocket.recv()
        print(f"Config response: {config_response}")

        # 2. Giả lập một đoạn âm thanh (1 giây noise) dạng Float32
        # Tương đương với dữ liệu mà frontend (VAD) sẽ gửi sau khi bạn nói xong
        duration = 1.0  # giây
        sample_rate = 16000
        samples = np.random.uniform(-0.1, 0.1, int(sample_rate * duration)).astype(np.float32)

        print(f"Đang gửi {len(samples)} samples âm thanh...")
        await websocket.send(samples.tobytes())

        # 3. Chờ nhận kết quả transcript từ backend
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            data = json.loads(response)
            print(f"Kết quả từ Server: {json.dumps(data, ensure_ascii=False, indent=2)}")
        except asyncio.TimeoutError:
            print("Hết thời gian chờ phản hồi từ server.")

if __name__ == "__main__":
    asyncio.run(test_stt())
