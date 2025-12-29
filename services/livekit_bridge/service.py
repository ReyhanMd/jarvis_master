"""
LiveKit Bridge Service

Connects to CaptureService WebSocket (port 8765) and publishes frames to LiveKit room.
This allows the Vision service to subscribe to LiveKit for real-time frame processing.
"""

import asyncio
import json
import sys
import os
import base64
from typing import Optional
from io import BytesIO
from loguru import logger

# Add parent directory to path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

try:
    import websockets
except ImportError:
    logger.error("websockets not installed. Install with: pip install websockets")
    sys.exit(1)

try:
    from livekit import api, rtc
    from livekit.protocol import video as proto_video
    import numpy as np
    from PIL import Image
    HAS_LIVEKIT = True
except ImportError:
    logger.warning("livekit not installed. Install with: pip install livekit")
    logger.warning("Also ensure Pillow and numpy are installed")
    HAS_LIVEKIT = False


class LiveKitBridge:
    """
    Bridges CaptureService WebSocket frames to LiveKit room.
    
    Flow:
    1. Connect to CaptureService WebSocket (ws://localhost:8765/capture)
    2. Connect to LiveKit room (shail-vision)
    3. Publish JPEG frames as video track to LiveKit
    4. Vision service subscribes to LiveKit room for processing
    """
    
    def __init__(
        self,
        capture_ws_url: str = "ws://localhost:8765/capture",
        livekit_url: str = "ws://localhost:7880",
        livekit_api_key: Optional[str] = None,
        livekit_api_secret: Optional[str] = None,
        room_name: str = "shail-vision"
    ):
        self.capture_ws_url = capture_ws_url
        self.livekit_url = livekit_url
        self.livekit_api_key = livekit_api_key or os.getenv("LIVEKIT_API_KEY", "")
        self.livekit_api_secret = livekit_api_secret or os.getenv("LIVEKIT_API_SECRET", "")
        self.room_name = room_name
        
        self._running = False
        self._capture_ws: Optional[websockets.WebSocketServerProtocol] = None
        self._room: Optional[rtc.Room] = None
        self._video_track: Optional[rtc.LocalVideoTrack] = None
        self._video_source: Optional[JPEGVideoSource] = None
        self._frame_count = 0
        
    async def start(self):
        """Start the bridge service"""
        if not HAS_LIVEKIT:
            logger.error("LiveKit SDK not available. Cannot start bridge.")
            return
            
        self._running = True
        logger.info(f"🌉 Starting LiveKit Bridge")
        logger.info(f"   CaptureService: {self.capture_ws_url}")
        logger.info(f"   LiveKit Server: {self.livekit_url}")
        logger.info(f"   Room: {self.room_name}")
        
        # Connect to LiveKit room first
        try:
            await self._connect_to_livekit()
        except Exception as e:
            logger.error(f"Failed to connect to LiveKit: {e}")
            logger.info("Make sure LiveKit server is running. See README.md for setup.")
            return
        
        # Then connect to CaptureService and bridge frames
        while self._running:
            try:
                await self._bridge_frames()
            except Exception as e:
                logger.warning(f"Bridge error: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
    
    async def _connect_to_livekit(self):
        """Connect to LiveKit room and create video track"""
        logger.info("🔌 Connecting to LiveKit room...")
        
        # Create access token
        token = api.AccessToken(self.livekit_api_key, self.livekit_api_secret) \
            .with_identity("bridge-service") \
            .with_name("CaptureService Bridge") \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=False
            ))
        
        # Connect to room
        self._room = rtc.Room()
        
        @self._room.on("connected")
        def on_connected():
            logger.info("✅ Connected to LiveKit room")
        
        @self._room.on("disconnected")
        def on_disconnected():
            logger.warning("❌ Disconnected from LiveKit room")
        
        @self._room.on("track_published")
        def on_track_published(publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
            logger.info(f"📹 Video track published: {publication.sid}")
        
        await self._room.connect(self.livekit_url, token.to_jwt())
        
        # Create local video track for publishing frames
        # We'll use a custom video source that accepts JPEG frames
        source = JPEGVideoSource(width=1920, height=1080)
        self._video_track = rtc.LocalVideoTrack.create_video_track("screen-capture", source)
        self._video_source = source  # Store reference for frame injection
        
        # Publish track
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
        await self._room.local_participant.publish_track(self._video_track, options)
        logger.info("📤 Published video track to LiveKit room")
    
    async def _bridge_frames(self):
        """Bridge frames from CaptureService to LiveKit"""
        logger.info(f"📡 Connecting to CaptureService at {self.capture_ws_url}...")
        
        async with websockets.connect(self.capture_ws_url) as ws:
            self._capture_ws = ws
            logger.info("✅ Connected to CaptureService")
            
            async for message in ws:
                if not self._running:
                    break
                
                if isinstance(message, bytes):
                    # JPEG frame received
                    self._frame_count += 1
                    
                    if self._frame_count % 30 == 0:  # Log every second at 30 FPS
                        logger.debug(f"📸 Bridged {self._frame_count} frames to LiveKit")
                    
                    # Send frame to LiveKit video track
                    if self._video_source:
                        await self._video_source.on_frame(message)
                
                else:
                    # JSON message (heartbeat)
                    try:
                        data = json.loads(message)
                        if data.get("type") == "heartbeat":
                            logger.debug(f"💓 Capture heartbeat: {data.get('frames_captured')} frames")
                    except json.JSONDecodeError:
                        pass
    
    async def stop(self):
        """Stop the bridge service"""
        logger.info("🛑 Stopping LiveKit Bridge...")
        self._running = False
        
        if self._room:
            await self._room.disconnect()
        
        if self._capture_ws:
            await self._capture_ws.close()
        
        logger.info("✅ LiveKit Bridge stopped")


class JPEGVideoSource(rtc.VideoSource):
    """
    Custom video source that accepts JPEG frames and converts them to video frames.
    Uses LiveKit's VideoSource API to publish frames.
    """
    
    def __init__(self, width: int = 1920, height: int = 1080):
        # Initialize video source with RGBA format
        super().__init__(
            rtc.VideoResolution(width=width, height=height),
            rtc.VideoBufferType.RGBA
        )
        self.width = width
        self.height = height
    
    async def on_frame(self, jpeg_data: bytes):
        """
        Process JPEG frame and emit as video frame to LiveKit.
        """
        try:
            # Decode JPEG to PIL Image
            image = Image.open(BytesIO(jpeg_data))
            
            # Get actual dimensions
            img_width, img_height = image.size
            
            # Convert to RGBA if needed
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            
            # Resize to expected resolution if needed
            if (img_width, img_height) != (self.width, self.height):
                image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
            
            # Convert to numpy array (RGBA format)
            frame_array = np.array(image, dtype=np.uint8)
            
            # Create VideoFrame using LiveKit's API
            # Note: LiveKit SDK may have different API - adjust as needed
            frame = rtc.VideoFrame(
                width=self.width,
                height=self.height,
                data=frame_array.tobytes(),
                format=rtc.VideoBufferType.RGBA
            )
            
            # Capture and publish frame
            self.capture_frame(frame)
            
        except Exception as e:
            logger.error(f"Error processing JPEG frame: {e}", exc_info=True)


async def main():
    """Main entry point"""
    bridge = LiveKitBridge()
    
    try:
        await bridge.start()
    except KeyboardInterrupt:
        logger.info("👋 Stopping bridge...")
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())

