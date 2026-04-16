"""
Fish Speech TTS service for voice cloning.
Communicates with a Fish Speech API server (separate process) via HTTP.
Loads voice reference audio from disk and sends inline with each TTS request.
"""

import asyncio
import base64
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings


class FishTTSService:
    """Voice-cloning TTS via Fish Speech HTTP API."""

    SAMPLE_RATE = 44100  # Fish Speech outputs 44.1kHz

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._available: bool = False
        # voice_id -> {"audio_b64": str, "transcript": str}
        self._voices: dict[str, dict] = {}
        self._default_voice: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"Accept": "application/json"},
                timeout=httpx.Timeout(60.0, connect=10.0)
            )
        return self._client

    @property
    def sample_rate(self) -> int:
        return self.SAMPLE_RATE

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def available_voices(self) -> list[str]:
        return list(self._voices.keys())

    async def initialize(self) -> bool:
        """
        Test connection to Fish Speech server and fetch initial voice list.
        """
        # Test server connectivity via health endpoint
        health_url = f"{settings.FISH_TTS_URL}/"
        try:
            client = await self._get_client()
            response = await client.get(health_url, timeout=5.0)
            if response.status_code == 200:
                self._available = True
                
                # Fetch initial voices from Fish Server
                await self.list_references()

                print(
                    f"[Fish TTS] Connected to {settings.FISH_TTS_URL}, "
                    f"found {len(self._voices)} native reference voice(s)"
                )
                # Warmup to trigger Triton compilation
                asyncio.create_task(self.warmup())
            else:
                self._available = False
                print(
                    f"[Fish TTS] Server reached but health check failed ({response.status_code}): {health_url}"
                )
        except Exception as e:
            self._available = False
            print(f"[Fish TTS] Server not reachable at {health_url}: {e}")

        return self._available

    async def list_references(self) -> list[str]:
        """Fetch the list of reference voice IDs from the Fish Server."""
        try:
            client = await self._get_client()
            response = await client.get(f"{settings.FISH_TTS_URL}/v1/references/list")
            if response.status_code == 200:
                data = response.json()
                ids = data.get("reference_ids", [])
                
                # Update our local record (just the IDs for now)
                # We use a simple dict as a set/cache
                self._voices = {vid: {"id": vid} for vid in ids}
                if ids and self._default_voice is None:
                    self._default_voice = ids[0]
                
                return ids
        except Exception as e:
            print(f"[Fish TTS] Failed to list references: {e}")
        return []

    async def add_reference(self, voice_id: str, audio_bytes: bytes, text: str) -> bool:
        """Upload a new reference voice to the Fish Server."""
        try:
            client = await self._get_client()
            files = {"audio": ("reference.wav", audio_bytes, "audio/wav")}
            data = {"id": voice_id, "text": text}
            
            response = await client.post(
                f"{settings.FISH_TTS_URL}/v1/references/add",
                data=data,
                files=files
            )
            
            if response.status_code in (200, 201):
                await self.list_references() # Refresh list
                return True
            else:
                print(f"[Fish TTS] Add reference failed ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"[Fish TTS] Error adding reference: {e}")
        return False

    async def delete_reference(self, voice_id: str) -> bool:
        """Delete a reference voice from the Fish Server."""
        try:
            client = await self._get_client()
            # The API documentation showed DELETE /v1/references/delete accepts Body
            response = await client.request(
                "DELETE",
                f"{settings.FISH_TTS_URL}/v1/references/delete",
                json={"reference_id": voice_id}
            )
            if response.status_code == 200:
                await self.list_references() # Refresh list
                return True
        except Exception as e:
            print(f"[Fish TTS] Failed to delete reference: {e}")
        return False

    async def warmup(self):
        """Send a small request to trigger Triton compilation."""
        if not self._voices:
            return

        voice_id = next(iter(self._voices))
        print(f"[Fish TTS] Starting warmup using native reference '{voice_id}'...")
        
        try:
            async for _ in self.synthesize_stream_pcm("Warmup.", voice=voice_id):
                pass
            print("[Fish TTS] Warmup complete")
        except Exception as e:
            print(f"[Fish TTS] Warmup failed: {e}")

    async def synthesize_stream_pcm(
        self,
        text: str,
        voice: Optional[str] = None,
        chunk_size: int = 8192,
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesize text using Fish Speech with voice cloning.
        Yields raw PCM s16le audio chunks at 44100Hz.
        """
        if not self._voices:
            print("[Fish TTS] No native voice references found on server")
            return

        voice_id = voice or self._default_voice
        if voice_id not in self._voices:
            # Fall back to default
            voice_id = self._default_voice
            if voice_id not in self._voices:
                print(f"[Fish TTS] Voice '{voice_id}' not found")
                return

        payload = {
            "text": text,
            "reference_id": voice_id,
            "chunk_length": 200,
            "format": "wav",
            "streaming": True,
            "normalize": True,
            "max_new_tokens": 1024,
            "top_p": 0.8,
            "repetition_penalty": 1.1,
            "temperature": 0.8,
            "sample_rate": self.SAMPLE_RATE,
        }

        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                f"{settings.FISH_TTS_URL}/v1/tts",
                json=payload,
                timeout=httpx.Timeout(120.0, connect=10.0),
            ) as response:
                if response.status_code != 200:
                    error_bytes = await response.aread()
                    print(f"[Fish TTS] Server error ({response.status_code}): {error_bytes.decode(errors='ignore')}")
                    return

                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    error_bytes = await response.aread()
                    print(f"[Fish TTS] Server returned JSON instead of audio: {error_bytes.decode(errors='ignore')}")
                    return

                # Robustly strip the WAV header and ensure 16-bit (2-byte) alignment
                header_stripped = False
                buffer = b""
                async for chunk in response.aiter_bytes(chunk_size):
                    if not chunk:
                        continue
                    
                    buffer += chunk
                    
                    if not header_stripped:
                        # Standard WAV headers end 8 bytes after the 'data' signature
                        data_idx = buffer.find(b"data")
                        if data_idx != -1 and len(buffer) >= data_idx + 8:
                            header_stripped = True
                            buffer = buffer[data_idx + 8:]
                        elif len(buffer) > 2048:
                            # Emergency fallback if 'data' is missing (don't buffer forever)
                            header_stripped = True
                            # Note: We likely have header junk here, but alignment is prioritized
                    
                    # Once header is gone, only yield full 2-byte samples
                    if header_stripped and len(buffer) >= 2:
                        even_len = (len(buffer) // 2) * 2
                        yield buffer[:even_len]
                        buffer = buffer[even_len:]

            # Mark available on success (in case it was unreachable at startup)
            if not self._available:
                self._available = True
                print("[Fish TTS] Server now reachable")

        except httpx.ConnectError:
            if self._available:
                self._available = False
                print("[Fish TTS] Server connection lost")
        except httpx.TimeoutException:
            print("[Fish TTS] Request timed out (compilation may still be in progress)")
        except httpx.HTTPStatusError as e:
            print(f"[Fish TTS] Server error: {e.response.status_code}")
        except Exception as e:
            print(f"[Fish TTS] Synthesis error: {type(e).__name__}: {e}")

    async def shutdown(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


fish_tts_service = FishTTSService()
