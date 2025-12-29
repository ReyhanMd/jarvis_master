"""
Vision Service - Screen frame analysis

Processes screen frames from LiveKit room for visual understanding.
Can also accept direct frame uploads via HTTP API.
"""

import asyncio
import io
import time
import sys
import os
from typing import Optional
from loguru import logger
from PIL import Image
from fastapi import FastAPI, UploadFile, File

# Handle imports for both module and direct script execution
# Add parent directory to path for direct script execution
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Try relative imports first (when run as module), then absolute (when run as script)
try:
    from .models import VisionResult, OCRResult, DetectedObject, BoundingBox
except (ImportError, ValueError):
    from vision.models import VisionResult, OCRResult, DetectedObject, BoundingBox

# Optional: OCR engine
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    logger.warning("pytesseract not installed - OCR will not be available")
    HAS_TESSERACT = False

# Optional: Vision-Language Model (e.g., GPT-4V, Claude Vision)
try:
    from anthropic import Anthropic
    HAS_VLM = True
except ImportError:
    logger.warning("anthropic not installed - VLM features will not be available")
    HAS_VLM = False


class VisionService:
    """
    Processes screen frames for visual understanding.
    
    Features:
    - OCR text extraction
    - Object detection (UI elements)
    - Screen description via VLM
    - Caching for performance
    - LiveKit subscription for real-time frame processing
    """
    
    def __init__(self, enable_livekit: bool = True):
        self.app = FastAPI(title="Shail Vision Service")
        self._setup_routes()
        self.frame_cache = {}
        self.enable_livekit = enable_livekit
        self._livekit_room = None
        self._processing_task = None
        
        # Initialize VLM client if available
        self.vlm_client = None
        if HAS_VLM:
            # Will be initialized with API key from env
            pass
        
        # LiveKit subscription will be started in start() method
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.post("/analyze", response_model=VisionResult)
        async def analyze_frame(file: UploadFile = File(...)):
            """Analyze a screen frame"""
            contents = await file.read()
            image = Image.open(io.BytesIO(contents))
            return await self.analyze(image)
        
        @self.app.post("/ocr", response_model=VisionResult)
        async def ocr_frame(file: UploadFile = File(...)):
            """Extract text from frame via OCR"""
            contents = await file.read()
            image = Image.open(io.BytesIO(contents))
            return await self.ocr(image)
        
        @self.app.post("/describe", response_model=VisionResult)
        async def describe_frame(file: UploadFile = File(...)):
            """Get natural language description of frame"""
            contents = await file.read()
            image = Image.open(io.BytesIO(contents))
            return await self.describe(image)
        
        @self.app.get("/health")
        async def health():
            """Health check"""
            return {
                "status": "ok",
                "ocr_available": HAS_TESSERACT,
                "vlm_available": HAS_VLM,
                "livekit_connected": self._livekit_room is not None
            }
        
        @self.app.post("/vision/analyze")
        async def analyze_from_livekit():
            """
            Trigger analysis of latest frame from LiveKit.
            Returns the most recent analysis result.
            """
            # Get latest frame from cache if available
            if self.frame_cache:
                latest_frame_id = max(self.frame_cache.keys())
                frame_data = self.frame_cache[latest_frame_id]
                image = Image.open(io.BytesIO(frame_data))
                return await self.analyze(image)
            else:
                return {"error": "No frames available from LiveKit"}
    
    async def analyze(self, image: Image.Image) -> VisionResult:
        """
        Full analysis of screen frame: OCR + detection + description
        """
        start_time = time.time()
        frame_id = f"frame_{int(time.time() * 1000)}"
        
        result = VisionResult(
            frame_id=frame_id,
            timestamp=time.time(),
            resolution=(image.width, image.height)
        )
        
        # Run OCR
        if HAS_TESSERACT:
            result.ocr_texts = await self._run_ocr(image)
        
        # Run object detection (placeholder)
        # result.detected_objects = await self._run_detection(image)
        
        # Run VLM description (optional, expensive)
        # result.description = await self._run_vlm(image)
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        
        logger.info(f"📊 Analyzed frame {frame_id}: {len(result.ocr_texts)} OCR results")
        
        return result
    
    async def ocr(self, image: Image.Image) -> VisionResult:
        """Extract text via OCR"""
        start_time = time.time()
        frame_id = f"frame_{int(time.time() * 1000)}"
        
        result = VisionResult(
            frame_id=frame_id,
            timestamp=time.time(),
            resolution=(image.width, image.height)
        )
        
        if HAS_TESSERACT:
            result.ocr_texts = await self._run_ocr(image)
        else:
            logger.warning("OCR requested but pytesseract not available")
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        
        return result
    
    async def describe(self, image: Image.Image) -> VisionResult:
        """Get natural language description via VLM"""
        start_time = time.time()
        frame_id = f"frame_{int(time.time() * 1000)}"
        
        result = VisionResult(
            frame_id=frame_id,
            timestamp=time.time(),
            resolution=(image.width, image.height)
        )
        
        if HAS_VLM:
            result.description = await self._run_vlm(image)
        else:
            logger.warning("VLM requested but not available")
            result.description = "VLM not available"
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        
        return result
    
    async def _run_ocr(self, image: Image.Image) -> list[OCRResult]:
        """Run OCR on image"""
        
        # Run in thread pool to avoid blocking
        def _ocr():
            # Get text with bounding boxes
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            
            results = []
            n_boxes = len(data['text'])
            
            for i in range(n_boxes):
                text = data['text'][i].strip()
                if not text:
                    continue
                
                confidence = float(data['conf'][i])
                if confidence < 50:  # Filter low confidence
                    continue
                
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                
                results.append(OCRResult(
                    text=text,
                    confidence=confidence / 100.0,
                    bbox=BoundingBox(x1=x, y1=y, x2=x+w, y2=y+h)
                ))
            
            return results
        
        return await asyncio.to_thread(_ocr)
    
    async def _run_vlm(self, image: Image.Image) -> str:
        """Run Vision-Language Model for description"""
        
        # Placeholder for VLM integration
        # In production, send to Claude Vision API, GPT-4V, etc.
        
        logger.info("🤖 Running VLM description (placeholder)")
        
        # Simulate processing
        await asyncio.sleep(0.1)
        
        return "Screen shows a desktop application with multiple windows and text elements."
    
    async def _start_livekit_subscription(self):
        """Subscribe to LiveKit room for real-time frame processing"""
        try:
            from livekit import api, rtc  # noqa: F401
            
            livekit_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
            api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
            api_secret = os.getenv("LIVEKIT_API_SECRET", "devsecret")
            room_name = os.getenv("LIVEKIT_ROOM", "shail-vision")
            
            logger.info(f"🔌 Connecting to LiveKit room: {room_name}")
            
            # Create access token
            token = api.AccessToken(api_key, api_secret) \
                .with_identity("vision-service") \
                .with_name("Vision Service") \
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_subscribe=True,
                    can_publish=False
                ))
            
            # Connect to room
            self._livekit_room = rtc.Room()
            
            @self._livekit_room.on("connected")
            def on_connected():
                logger.info("✅ Connected to LiveKit room")
            
            @self._livekit_room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.Track,
                publication: rtc.RemoteTrackPublication,
                participant: rtc.RemoteParticipant
            ):
                if track.kind == rtc.TrackKind.KIND_VIDEO:
                    logger.info(f"📹 Subscribed to video track: {publication.sid}")
                    asyncio.create_task(self._process_video_track(track))
            
            await self._livekit_room.connect(livekit_url, token.to_jwt())
            
        except ImportError:
            logger.warning("LiveKit not installed. Frame subscription disabled.")
            logger.warning("Install with: pip install livekit")
        except Exception as e:
            logger.error(f"Failed to connect to LiveKit: {e}")
            logger.info("Vision service will continue with HTTP API only")
    
    async def _process_video_track(self, track):
        """Process video frames from LiveKit track"""
        from livekit import rtc  # Import here to avoid issues if LiveKit not installed
        
        logger.info("🎥 Starting video track processing")
        
        # Sample every 1-2 seconds (at 30 FPS, that's every 30-60 frames)
        frame_interval = 30  # Process 1 frame per second
        frame_count = 0
        
        @track.on("frame_received")
        def on_frame(frame):
            nonlocal frame_count
            frame_count += 1
            
            # Process every Nth frame
            if frame_count % frame_interval == 0:
                asyncio.create_task(self._process_frame_from_livekit(frame))
        
        # Keep processing
        while True:
            await asyncio.sleep(1)
    
    async def _process_frame_from_livekit(self, frame):
        """Process a single frame from LiveKit"""
        try:
            # Convert LiveKit VideoFrame to PIL Image
            # Note: This depends on LiveKit SDK's frame format
            # You may need to adjust based on actual SDK API
            
            # For now, we'll store frame data and process it
            frame_id = f"livekit_{int(time.time() * 1000)}"
            
            # TODO: Convert frame.data to PIL Image
            # This requires understanding LiveKit's frame format
            # For MVP, we can log that frames are being received
            
            logger.debug(f"📸 Received frame {frame_id} from LiveKit")
            
            # Store frame for later analysis
            # self.frame_cache[frame_id] = frame_data
            
            # Optionally trigger analysis automatically
            # result = await self.analyze(image)
            # logger.info(f"📊 Analyzed frame {frame_id}: {len(result.ocr_texts)} OCR results")
            
        except Exception as e:
            logger.error(f"Error processing LiveKit frame: {e}")
    
    async def start(self, host: str = "0.0.0.0", port: int = 8081):
        """Start the Vision Service HTTP API"""
        import uvicorn
        
        # Start LiveKit subscription if enabled
        if self.enable_livekit:
            asyncio.create_task(self._start_livekit_subscription())
        
        logger.info(f"🚀 Starting Vision Service API on {host}:{port}")
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


# Main entry point
if __name__ == "__main__":
    service = VisionService()
    
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("👋 Vision service stopped")

