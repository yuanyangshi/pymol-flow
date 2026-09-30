"""Voice capture, speech recognition, and streaming audio synthesis package."""

from .audio import VOICE_HELPER_SCRIPT, VoiceRecorder, transcribe
from .speech import (
    SpeechPlayer,
    SpeechRequest,
    SpeechSignals,
    speech_payload,
    spoken_text,
)

__all__ = [
    "VOICE_HELPER_SCRIPT",
    "VoiceRecorder",
    "transcribe",
    "SpeechPlayer",
    "SpeechRequest",
    "SpeechSignals",
    "speech_payload",
    "spoken_text",
]
