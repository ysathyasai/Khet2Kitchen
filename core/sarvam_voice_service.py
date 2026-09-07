"""
Sarvam AI Service Layer for Khet2Kitchen (K2K).
Wraps Sarvam's Saaras (STT) and Bulbul (TTS) REST APIs.
"""

import hashlib
import io
import logging
import os
import re
from typing import Optional, Tuple
from django.conf import settings
from django.core.cache import cache
import requests

logger = logging.getLogger(__name__)

# BCP-47 Locale Map for Sarvam AI
SARVAM_LOCALE_MAP = {
    "hi": "hi-IN",
    "mr": "mr-IN",
    "te": "te-IN",
    "ta": "ta-IN",
    "kn": "kn-IN",
    "pa": "pa-IN",
    "gu": "gu-IN",
    "bn": "bn-IN",
    "ml": "ml-IN",
    "od": "od-IN",
    "en": "en-IN",
}

REVERSE_LOCALE_MAP = {v: k for k, v in SARVAM_LOCALE_MAP.items()}
REVERSE_LOCALE_MAP["unknown"] = "auto"


def clean_text_for_tts(text: str, language_code: str = "hi-IN") -> str:
    """
    Cleans markdown formatting, emojis, and symbols for natural Indic/English TTS pronunciation.
    """
    if not text:
        return ""
    # Currency normalization based on language
    if language_code and (language_code.startswith("en") or "en" in language_code.lower()):
        cleaned = text.replace("₹", " rupees ")
    else:
        cleaned = text.replace("₹", "रुपये ")

    cleaned = re.sub(r"[\*#_`~]", " ", cleaned)
    cleaned = re.sub(r"[🤖🔊🎤📢🌾⚠️🚨✨🏬🚜📦]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


PERSONALIZED_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:Hello|Hi|Hey|Greetings|Welcome(?:\s+back)?|Good\s+(?:morning|afternoon|evening))"
    r"(?:\s+back)?(?:\s+[A-Za-z]+(?:\s+[A-Za-z]+)*)?"
    r"[,!.:;–—\-]*\s*"
    r"|"
    r"(?:नमस्ते|नमस्कार|प्रणाम|स्वागत(?:\s+है)?)"
    r"(?:\s+[\u0900-\u097F]+(?:\s+[\u0900-\u097F]+)*(?:\s+जी)?)?"
    r"[,!।.:;–—\-]*\s*"
    r")",
    re.IGNORECASE,
)


def sanitize_for_tts(text: str) -> str:
    """
    Sanitizes LLM response text for high-hit-rate TTS caching:
    - Strips markdown formatting (*, _, #, `, >, bullet points).
    - Strips personalized conversational prefixes (e.g. 'Hello [Name],', 'Welcome back [Name]!').
    - Truncates spoken text to max 140 characters, cutting cleanly at the last full word or punctuation mark.
    """
    if not text:
        return ""

    s = text.strip()

    # 1. Strip markdown links [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)

    # 2. Strip markdown header lines (e.g. '### Order Status\n')
    s = re.sub(r"^\s*#{1,6}\s+[^\n]*\n+", "", s)

    # 3. Strip bullet markers, blockquotes, and headings at line starts
    s = re.sub(r"^\s*([>#+\-*•]+)\s*", "", s, flags=re.MULTILINE)

    # 4. Strip inline markdown markers: *, _, #, `, ~, >
    s = re.sub(r"[\*#_`~>]", " ", s)

    # 5. Remove emojis and visual icons
    s = re.sub(r"[🤖🔊🎤📢🌾⚠️🚨✨🏬🚜📦•\u2600-\u27BF]", "", s)

    # 6. Currency pronunciation normalization
    if re.search(r"[\u0900-\u097F]", s):
        s = s.replace("₹", " रुपये ")
    else:
        s = s.replace("₹", " rupees ")

    # 7. Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # 8. Strip personalized conversational prefixes (e.g., 'Hello [Name],', 'Welcome back [Name]!')
    for _ in range(2):
        trimmed = PERSONALIZED_PREFIX_PATTERN.sub("", s).strip()
        if trimmed:
            s = trimmed
        else:
            break

    if not s:
        return ""

    # Capitalize first character if lowercase
    s = s[0].upper() + s[1:]

    # 9. Truncate cleanly to max 140 characters at last full word or punctuation mark
    MAX_CHARS = 140
    if len(s) > MAX_CHARS:
        chunk = s[:MAX_CHARS]
        best_punct = -1
        for p in (". ", "! ", "? ", "। ", ".\n", "!\n", "?\n", "।\n"):
            idx = chunk.rfind(p)
            if idx > best_punct:
                best_punct = idx

        if best_punct >= 40:
            s = chunk[:best_punct + 1].strip()
        elif chunk[-1] in ".!?।":
            s = chunk.strip()
        else:
            last_space = chunk.rfind(" ")
            if last_space > 30:
                clean_chunk = chunk[:last_space].rstrip(" ,;:-–—")
                if clean_chunk and clean_chunk[-1] not in ".!?।":
                    clean_chunk += "."
                s = clean_chunk
            else:
                s = chunk.rstrip(" ,;:-–—") + "."

    return s


class SarvamVoiceService:
    @classmethod
    def get_api_key(cls) -> str:
        return (getattr(settings, "SARVAM_API_KEY", "") or os.getenv("SARVAM_API_KEY", "")).strip()

    @classmethod
    def get_base_url(cls) -> str:
        base = getattr(settings, "SARVAM_API_BASE_URL", "") or os.getenv("SARVAM_API_BASE_URL", "") or "https://api.sarvam.ai"
        return base.strip().rstrip("/")

    @classmethod
    def normalize_language_code(cls, lang: str) -> str:
        """Converts short code ('hi') or 'auto' to Sarvam BCP-47 locale ('hi-IN')."""
        if not lang or lang == "auto":
            return "hi-IN"
        if "-" in lang:
            return lang
        return SARVAM_LOCALE_MAP.get(lang.lower(), "hi-IN")

    @classmethod
    def extract_short_lang(cls, locale_str: str) -> str:
        """Converts BCP-47 locale ('hi-IN') to short code ('hi')."""
        if not locale_str:
            return "hi"
        if locale_str in REVERSE_LOCALE_MAP:
            return REVERSE_LOCALE_MAP[locale_str]
        return locale_str.split("-")[0].lower()

    # --------------------------------------------------------------------------
    # 1. Speech-to-Text (Saaras STT)
    # --------------------------------------------------------------------------
    @classmethod
    def transcribe_audio(cls, audio_file, language_hint: str = "unknown") -> Tuple[str, str]:
        """
        Transcribes raw audio (WAV, WebM, MP3).
        Sends language_code="unknown" (or explicit language_hint) to Sarvam.
        Returns: (transcript_text, detected_short_language)
        """
        api_key = cls.get_api_key()
        if not api_key:
            logger.warning("SARVAM_API_KEY missing.")
            return "", "auto"

        if hasattr(audio_file, "read"):
            if hasattr(audio_file, "seek"):
                audio_file.seek(0)
            audio_bytes = audio_file.read()
            if hasattr(audio_file, "seek"):
                audio_file.seek(0)
        elif isinstance(audio_file, (bytes, bytearray)):
            audio_bytes = bytes(audio_file)
        else:
            return "", "auto"

        if not audio_bytes:
            return "", "auto"

        filename = getattr(audio_file, "name", "audio.wav") or "audio.wav"
        content_type = getattr(audio_file, "content_type", "") or "audio/wav"
        if "webm" in filename.lower() and "webm" not in content_type:
            content_type = "audio/webm"

        headers = {"api-subscription-key": api_key}
        files = {"file": (filename, io.BytesIO(audio_bytes), content_type)}
        target_stt_lang = language_hint if language_hint and language_hint not in ("auto", "unknown") else "unknown"
        data = {
            "language_code": target_stt_lang,  # "unknown" for auto Indic detection
            "model": "saaras:v3",
        }

        url = f"{cls.get_base_url()}/speech-to-text"
        try:
            res = requests.post(url, headers=headers, files=files, data=data, timeout=25)
            if res.status_code == 200:
                result = res.json()
                transcript = result.get("transcript", "").strip()
                detected_bcp47 = result.get("language_code", "unknown")
                short_lang = cls.extract_short_lang(detected_bcp47)
                logger.info("Sarvam STT success: '%s' [%s -> %s]", transcript, detected_bcp47, short_lang)
                return transcript, short_lang

            if res.status_code in (402, 403, 429) or "credit" in res.text.lower():
                logger.warning("Sarvam STT credits exhausted or limited (HTTP %d: %s). Falling back gracefully.", res.status_code, res.text[:200])
            else:
                logger.warning("Sarvam STT HTTP %d: %s", res.status_code, res.text[:250])
            return "", "auto"
        except Exception as e:
            logger.exception("Sarvam STT failed: %s", e)
            return "", "auto"

    # --------------------------------------------------------------------------
    # 2. Text-to-Speech (Bulbul TTS)
    # --------------------------------------------------------------------------
    @classmethod
    def synthesize_speech(
        cls,
        text: str,
        target_language_code: str = "hi-IN",
        speaker: str = "shubh",     # Universal speaker across all 8 Indic languages + English
        model: str = "bulbul:v3",
    ) -> Optional[str]:
        """
        Synthesizes spoken Indic or Indian English audio from text.
        Returns: base64-encoded WAV string or None (falls back cleanly to Web Native Speech).
        """
        if not text or not text.strip():
            return None

        language_code = cls.normalize_language_code(target_language_code)
        sanitized_text = sanitize_for_tts(text)
        if not sanitized_text:
            return None

        # Build deterministic cache key using sanitized text, speaker, and language_code
        key = f"sarvam_tts_{hashlib.md5(f'{sanitized_text}:{speaker}:{language_code}'.encode('utf-8')).hexdigest()}"
        cached_audio = cache.get(key)
        if cached_audio:
            print(f"[SARVAM CACHE HIT] Reusing cached audio: {key}", flush=True)
            logger.info("Sarvam TTS cache hit for key: %s", key)
            return cached_audio

        api_key = cls.get_api_key()
        if not api_key:
            return None

        headers = {
            "api-subscription-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": [sanitized_text],
            "target_language_code": language_code,
            "speaker": speaker,
            "pitch": 0,
            "pace": 0.95,
            "loudness": 1.5,
            "speech_sample_rate": 22050,
            "enable_preprocessing": True,
            "model": model,
        }

        url = f"{cls.get_base_url()}/text-to-speech"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                audios = res.json().get("audios", [])
                if audios:
                    audio_data = audios[0]  # Base64 string
                    cache.set(key, audio_data, timeout=604800)  # 7 days
                    print(f"[SARVAM API CALL] Synthesized and cached {len(sanitized_text)} chars: {key}", flush=True)
                    logger.info("Sarvam TTS success & cached: %s (%d chars)", key, len(audio_data))
                    return audio_data

            if res.status_code in (402, 403, 429) or "credit" in res.text.lower() or "quota" in res.text.lower():
                logger.warning("Sarvam TTS credits exhausted (HTTP %d: %s). Seamlessly falling back to Web Native Speech.", res.status_code, res.text[:200])
            else:
                logger.warning("Sarvam TTS HTTP %d: %s", res.status_code, res.text[:250])
            return None
        except Exception as e:
            logger.exception("Sarvam TTS failed: %s", e)
            return None
