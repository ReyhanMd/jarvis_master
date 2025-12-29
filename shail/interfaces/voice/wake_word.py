"""Wake word detection for "Hey SHAIL"."""

import logging
from typing import Callable, Optional
import threading
import time

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Detects "Hey SHAIL" wake word to trigger the popup.
    
    Supports:
    - macOS speech recognition (native)
    - Whisper (local)
    - Keyword spotting (future)
    """
    
    def __init__(self, callback: Optional[Callable] = None):
        """
        Initialize wake word detector.
        
        Args:
            callback: Function to call when wake word is detected
        """
        self.callback = callback
        self.is_listening = False
        self.detection_thread = None
        logger.info("Initialized WakeWordDetector")
    
    def start_listening(self):
        """Start listening for wake word."""
        if self.is_listening:
            return
        
        self.is_listening = True
        
        # Try macOS speech recognition first
        try:
            import speech_recognition as sr
            self._start_speech_recognition()
            return
        except ImportError:
            logger.warning("speech_recognition not available, using stub")
        
        # Fallback: stub implementation
        self._start_stub_listening()
    
    def _start_speech_recognition(self):
        """Start using speech recognition library."""
        import speech_recognition as sr
        
        def listen_loop():
            r = sr.Recognizer()
            mic = sr.Microphone()
            
            with mic as source:
                r.adjust_for_ambient_noise(source)
            
            logger.info("Listening for 'Hey SHAIL'...")
            
            while self.is_listening:
                try:
                    with mic as source:
                        audio = r.listen(source, timeout=1, phrase_time_limit=2)
                    
                    try:
                        text = r.recognize_google(audio).lower()
                        if "hey shail" in text or "hey sail" in text:
                            logger.info("Wake word detected!")
                            if self.callback:
                                self.callback()
                    except sr.UnknownValueError:
                        pass
                    except sr.RequestError as e:
                        logger.error(f"Speech recognition error: {e}")
                
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in listen loop: {e}")
                    time.sleep(1)
        
        self.detection_thread = threading.Thread(target=listen_loop, daemon=True)
        self.detection_thread.start()
    
    def _start_stub_listening(self):
        """Stub implementation for testing."""
        logger.info("Wake word detection (stub mode) - use keyboard shortcut or click mic")
    
    def stop_listening(self):
        """Stop listening for wake word."""
        self.is_listening = False
        if self.detection_thread:
            self.detection_thread.join(timeout=1)
        logger.info("Stopped listening for wake word")
    
    def trigger(self):
        """Manually trigger wake word (for testing or keyboard shortcut)."""
        logger.info("Wake word manually triggered")
        if self.callback:
            self.callback()
