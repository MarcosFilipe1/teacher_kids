import os
import io
import threading
import queue
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
WAKE_WORDS = ["hey professora", "oi professora", "professora"]
AUDIO_CACHE_DIR = Path("static/sounds/cache")
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ─── TTS (Texto → Voz) ───────────────────────────────────────────────────────

def text_to_speech(text: str, voice: str = "nova") -> bytes:
    """
    Converte texto para áudio usando OpenAI TTS.
    voice: nova (feminina, animada) | alloy | echo | fable | onyx | shimmer
    Retorna bytes MP3.
    """
    try:
        import httpx
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "tts-1",
                "input": text,
                "voice": voice,
                "speed": 0.95,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"[TTS] Erro: {e}")
        return b""


def tts_cached(text: str, voice: str = "nova") -> str:
    """
    TTS com cache em disco. Retorna caminho relativo do arquivo MP3.
    Evita rechamar a API para frases repetidas (ex: feedback padrão).
    """
    import hashlib
    key = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()
    path = AUDIO_CACHE_DIR / f"{key}.mp3"
    if not path.exists():
        audio = text_to_speech(text, voice)
        if audio:
            path.write_bytes(audio)
        else:
            return ""
    return str(path)


# ─── STT (Voz → Texto) via Whisper ───────────────────────────────────────────

def speech_to_text(audio_bytes: bytes, language: str = "pt") -> str:
    """
    Transcreve áudio para texto usando OpenAI Whisper.
    language: 'pt' para português, 'en' para inglês, None para auto-detect.
    """
    try:
        import httpx
        files = {"file": ("audio.webm", audio_bytes, "audio/webm")}
        data = {
            "model": "whisper-1",
            "language": language,
            "prompt": "Criança de 6 anos falando palavras em português e inglês.",
        }
        response = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files=files,
            data=data,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()
    except Exception as e:
        logger.error(f"[STT] Erro: {e}")
        return ""


# ─── Wake Word (OpenWakeWord via subprocess) ──────────────────────────────────

class WakeWordDetector:
    """
    Escuta continuamente o microfone e dispara callback quando detecta wake word.
    Usa openwakeword se disponível, caso contrário usa detecção simples por energia.
    """

    def __init__(self, on_wake_callback, sensitivity: float = 0.5):
        self.on_wake = on_wake_callback
        self.sensitivity = sensitivity
        self._running = False
        self._thread = None
        self._audio_queue = queue.Queue()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("[WakeWord] Detector iniciado")

    def stop(self):
        self._running = False
        logger.info("[WakeWord] Detector parado")

    def _listen_loop(self):
        try:
            self._listen_with_openwakeword()
        except ImportError:
            logger.warning("[WakeWord] openwakeword não instalado, usando fallback de energia")
            self._listen_fallback()

    def _listen_with_openwakeword(self):
        import openwakeword
        import pyaudio
        import numpy as np
        from openwakeword.model import Model

        oww_model = Model(
            wakeword_models=["hey_jarvis"],  # trocar por modelo custom quando treinar
            inference_framework="tflite",
        )

        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=16000, channels=1, format=pyaudio.paInt16,
            input=True, frames_per_buffer=1280,
        )

        logger.info("[WakeWord] Ouvindo... diga 'Hey Professora'")
        while self._running:
            chunk = stream.read(1280, exception_on_overflow=False)
            audio = np.frombuffer(chunk, dtype=np.int16)
            prediction = oww_model.predict(audio)
            for score in prediction.values():
                if score >= self.sensitivity:
                    logger.info(f"[WakeWord] Detectado! score={score:.2f}")
                    self.on_wake()
                    time.sleep(2)  # cooldown
                    break

        stream.stop_stream()
        stream.close()
        pa.terminate()

    def _listen_fallback(self):
        """Fallback: botão físico via stdin ou endpoint HTTP (sem mic)."""
        logger.info("[WakeWord] Fallback ativo — use POST /api/wake para simular")
        while self._running:
            time.sleep(1)


# ─── Gravação de áudio do browser ────────────────────────────────────────────

def estimate_tts_cost(text: str) -> float:
    """Estimativa de custo OpenAI TTS-1: $15 por 1M caracteres."""
    return len(text) * 0.000015


def estimate_stt_cost(duration_seconds: float) -> float:
    """Estimativa de custo Whisper: $0.006 por minuto."""
    return (duration_seconds / 60) * 0.006
