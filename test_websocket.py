#!/usr/bin/env python3
"""
Simple WebSocket test to verify the endpoint is working
"""

import asyncio
import websockets
import json
import sys

async def test_websocket():
    uri = "ws://localhost:8000/ws/brain"
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected successfully!")
            
            # Send a ping
            await websocket.send(json.dumps({"type": "ping"}))
            print("📤 Sent ping")
            
            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"📥 Received: {response}")
            
            # Parse response
            data = json.loads(response)
            if data.get("type") == "pong":
                print("✅ Ping/pong working!")
            else:
                print(f"⚠️  Unexpected response type: {data.get('type')}")
                
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ WebSocket connection failed: {e}")
        print(f"   Status code: {e.status_code}")
        if e.headers:
            print(f"   Headers: {e.headers}")
        return False
    except ConnectionRefusedError:
        print("❌ Connection refused - backend not running on port 8000")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(test_websocket())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted")
        sys.exit(1)
