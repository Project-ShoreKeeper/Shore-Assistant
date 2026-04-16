# Fish Speech v1.5 Setup (Docker Method)

Running Fish Speech via Docker is the most stable method for Windows 11 as it handles all CUDA/ONNX DLL dependencies automatically.

## 1. Prerequisites
- **Docker Desktop** installed and running.
- **NVIDIA Container Toolkit** support (Included in Docker Desktop with WSL2 backend).

## 2. Installation & Setup

### Clone and Pull Checkpoints
If you haven't already, clone the repo and download the v1.5.1 model files:

```powershell
# 1. Clone at v1.5 tag
git clone --branch v1.5.1 https://github.com/fishaudio/fish-speech.git
cd fish-speech

# 2. Download v1.5 checkpoint (~2GB)
# (Using the robust Zero-CLI method)
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='fishaudio/fish-speech-1.5', local_dir='checkpoints/fish-speech-1.5')"
```

### Start the Server (Docker)
In the `fish-speech` directory, run:

```powershell
# Build and start the container in the background
docker compose up -d --build
```

> [!TIP]
> This command will build the image (takes 3-5 minutes on the first run) and start the API server on port **8080**.

## 3. Monitoring & Verification

### Check Logs
Verify the server is running and the GPU is detected:
```powershell
docker compose logs -f
```

### Health Check
Test the connection from another terminal:
```powershell
curl http://localhost:8080/v1/health
```
*(Expect: `{"status":"ok"}`)*

## 4. Using Voice Cloning
The `docker-compose.yaml` is configured to mount your project's `voices/` directory automatically.

1.  Place your reference audios in `Shore-Assistant/voices/`.
2.  In the Shore Assistant UI, open **Settings** (gear icon).
3.  Change **Voice Mode** to `Fish Speech`.
4.  Your voices from the `voices/` folder will appear in the dropdown.

## Troubleshooting
- **GPU not detected**: Ensure Docker Desktop is using the **WSL2** backend and you have the latest NVIDIA drivers on your host Windows machine.
- **Port Conflict**: If port 8080 is already in use, you can change the mapping in `docker-compose.yaml`.
