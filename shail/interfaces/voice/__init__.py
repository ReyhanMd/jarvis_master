"""Voice interface for SHAIL.

This module provides voice activation and speech recognition capabilities.
"""

from shail.interfaces.voice.wake_word import WakeWordDetector
from shail.interfaces.voice.speech_to_text import SpeechToText

__all__ = ["WakeWordDetector", "SpeechToText"]
