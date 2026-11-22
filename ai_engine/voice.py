"""Mülakat provası için ses: soruyu sesli okuma (macOS 'say', Türkçe ses) ve cevabı yazıya çevirme (yerel Whisper).

Hiçbir ses dosyası internete gönderilmez:
- Konuşma: macOS'un yerleşik Türkçe sesi (varsayılan 'Yelda') → WAV.
- Tanıma: mlx-whisper (Apple Silicon'da yerel). Model ilk kullanımda HuggingFace'ten bir kez indirilir.
"""
import hashlib
import io
import os
import subprocess
import tempfile
import wave

import numpy as np

from app.logger import get_logger

log = get_logger("voice")

TTS_VOICE = os.getenv("TTS_VOICE", "Yelda")
TTS_VOICE_EN = os.getenv("TTS_VOICE_EN", "Samantha")
TTS_RATE = int(os.getenv("TTS_RATE", "185"))  # kelime/dk; 175-190 doğal mülakat hızı
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-small-mlx")
_TTS_CACHE = {}


class VoiceError(RuntimeError):
    pass


def _voice_for(lang="tr"):
    return TTS_VOICE_EN if lang == "en" else TTS_VOICE


def tts_available(lang="tr"):
    target = _voice_for(lang)
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[0] == target for line in out.splitlines() if line.strip())


def speak(text, lang="tr"):
    """Metni yerel macOS sesiyle okur (tr: Yelda, en: Samantha); WAV baytları döner (aynı metin önbellekten)."""
    voice_name = _voice_for(lang)
    key = hashlib.sha1(f"{voice_name}|{TTS_RATE}|{text}".encode()).hexdigest()
    if key in _TTS_CACHE:
        return _TTS_CACHE[key]
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = os.path.join(d, "s.aiff"), os.path.join(d, "s.wav")
        try:
            subprocess.run(["say", "-v", voice_name, "-r", str(TTS_RATE), "-o", aiff, text], check=True, timeout=60,
                           capture_output=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", aiff, wav], check=True, timeout=60,
                           capture_output=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise VoiceError(f"Ses üretilemedi: {e}") from e
        with open(wav, "rb") as f:
            data = f.read()
    _TTS_CACHE[key] = data
    return data


def stt_available():
    import importlib.util
    return importlib.util.find_spec("mlx_whisper") is not None


def wav_to_array(data: bytes):
    """WAV baytları → 16 kHz mono float32 (Whisper'ın beklediği biçim). ffmpeg gerekmez."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(n)
    except (wave.Error, EOFError) as e:
        raise VoiceError(f"Ses kaydı okunamadı: {e}") from e
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise VoiceError(f"Desteklenmeyen ses biçimi ({width * 8} bit)")
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32) / float(np.iinfo(dtype).max)
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if rate != 16000 and len(audio):
        dur = len(audio) / rate
        audio = np.interp(np.linspace(0, dur, int(dur * 16000), endpoint=False),
                          np.arange(len(audio)) / rate, audio).astype(np.float32)
    return audio


def transcribe_with_stats(data: bytes, prompt="", language="tr"):
    """Kaydı yazıya çevirir ve ses süresini (sn) döner: {"text": str, "duration_sec": float}."""
    if not stt_available():
        raise VoiceError("Konuşma tanıma kurulu değil: venv/bin/pip install mlx-whisper")
    import mlx_whisper
    audio = wav_to_array(data)
    dur = round(len(audio) / 16000.0, 1)
    if len(audio) < 16000 * 0.5:
        return {"text": "", "duration_sec": dur}
    try:
        res = mlx_whisper.transcribe(audio, path_or_hf_repo=WHISPER_MODEL, language=language,
                                     initial_prompt=(prompt or "")[:200] or None, fp16=True,
                                     condition_on_previous_text=False)
    except Exception as e:  # model indirilemedi / bellek vb.
        log.exception("Konuşma tanıma başarısız")
        raise VoiceError(f"Konuşma yazıya çevrilemedi: {e}") from e
    return {"text": " ".join((res.get("text") or "").split()), "duration_sec": dur}


def transcribe(data: bytes, prompt="", language="tr"):
    """Kaydı yazıya çevirir. prompt: soru metni (terimleri doğru yazması için ipucu)."""
    return transcribe_with_stats(data, prompt=prompt, language=language)["text"]
