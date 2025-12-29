"""Speech-to-text conversion for SHAIL."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SpeechToText:
    """
    Converts speech to text for SHAIL.
    
    Supports:
    - macOS speech recognition (native)
    - Whisper (local)
    - Google Speech API (cloud)
    """
    
    def __init__(self, method: str = "auto"):
        """
        Initialize speech-to-text.
        
        Args:
            method: Recognition method ("auto", "macos", "whisper", "google")
        """
        self.method = method
        logger.info(f"Initialized SpeechToText (method: {method})")
    
    def transcribe(self, audio_source: Optional[str] = None) -> str:
        """
        Transcribe speech to text.
        
        Args:
            audio_source: Optional path to audio file (None for microphone)
            
        Returns:
            Transcribed text
        """
        # Try macOS speech recognition
        if self.method in ("auto", "macos"):
            try:
                return self._transcribe_macos(audio_source)
            except Exception as e:
                logger.warning(f"macOS recognition failed: {e}")
                if self.method == "macos":
                    raise
        
        # Try Whisper
        if self.method in ("auto", "whisper"):
            try:
                return self._transcribe_whisper(audio_source)
            except Exception as e:
                logger.warning(f"Whisper recognition failed: {e}")
                if self.method == "whisper":
                    raise
        
        # Try Google
        if self.method in ("auto", "google"):
            try:
                return self._transcribe_google(audio_source)
            except Exception as e:
                logger.warning(f"Google recognition failed: {e}")
                if self.method == "google":
                    raise
        
        # Fallback
        logger.warning("All speech recognition methods failed, returning stub")
        return "[Speech recognition not available]"
    
    def _transcribe_macos(self, audio_source: Optional[str]) -> str:
        """Use macOS native speech recognition."""
        try:
            import speech_recognition as sr
            
            r = sr.Recognizer()
            
            if audio_source:
                with sr.AudioFile(audio_source) as source:
                    audio = r.record(source)
            else:
                mic = sr.Microphone()
                with mic as source:
                    r.adjust_for_ambient_noise(source)
                    audio = r.listen(source, timeout=5)
            
            # Use macOS recognition
            text = r.recognize_google(audio)
            return text
        
        except ImportError:
            raise RuntimeError("speech_recognition library not installed")
        except Exception as e:
            raise RuntimeError(f"macOS recognition error: {e}")
    
    def _transcribe_whisper(self, audio_source: Optional[str]) -> str:
        """Use Whisper for local transcription."""
        try:
            import whisper
            
            model = whisper.load_model("base")
            
            if audio_source:
                result = model.transcribe(audio_source)
            else:
                # Would need to record audio first
                raise NotImplementedError("Microphone input for Whisper not yet implemented")
            
            return result["text"]
        
        except ImportError:
            raise RuntimeError("whisper library not installed")
        except Exception as e:
            raise RuntimeError(f"Whisper recognition error: {e}")
    
    def _transcribe_google(self, audio_source: Optional[str]) -> str:
        """Use Google Speech API."""
        try:
            import speech_recognition as sr
            
            r = sr.Recognizer()
            
            if audio_source:
                with sr.AudioFile(audio_source) as source:
                    audio = r.record(source)
            else:
                mic = sr.Microphone()
                with mic as source:
                    r.adjust_for_ambient_noise(source)
                    audio = r.listen(source, timeout=5)
            
            text = r.recognize_google(audio)
            return text
        
        except ImportError:
            raise RuntimeError("speech_recognition library not installed")
        except Exception as e:
            raise RuntimeError(f"Google recognition error: {e}")
