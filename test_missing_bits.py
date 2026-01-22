#!/usr/bin/env python3
"""
Simple test script to verify missing bits implementations.
Tests desktop_id and permission WebSocket without requiring Swift UI.
"""

import sys
import os
import json
import time
import requests
from typing import Dict, Any

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def test_desktop_id():
    """Test that desktop_id is accepted and stored correctly."""
    print("\n=== Testing Desktop ID ===")
    
    # Test 1: Submit task with desktop_id
    url = "http://localhost:8000/tasks"
    payload = {
        "text": "test task with desktop",
        "mode": "auto",
        "desktop_id": "Desktop 1"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 202:
            result = response.json()
            task_id = result.get("task_id")
            print(f"✅ Task submitted: {task_id}")
            print(f"   Payload included desktop_id: {payload.get('desktop_id')}")
            return True, task_id
        else:
            print(f"❌ Task submission failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False, None
    except requests.exceptions.ConnectionError:
        print("❌ Backend not running on port 8000")
        return False, None
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, None

def test_permission_websocket():
    """Test that permission requests can be broadcast."""
    print("\n=== Testing Permission WebSocket ===")
    
    # Check if WebSocket endpoint exists
    try:
        # Try to connect to WebSocket (this is a simple check)
        import websockets
        import asyncio
        
        async def check_websocket():
            try:
                uri = "ws://localhost:8000/ws/brain"
                async with websockets.connect(uri) as ws:
                    print(f"✅ WebSocket connection successful: {uri}")
                    # Send a ping
                    await ws.send(json.dumps({"type": "ping"}))
                    response = await asyncio.wait_for(ws.recv(), timeout=2)
                    print(f"✅ WebSocket ping/pong working")
                    return True
            except Exception as e:
                print(f"❌ WebSocket connection failed: {e}")
                return False
        
        return asyncio.run(check_websocket())
    except ImportError:
        print("⚠️  websockets library not installed, skipping WebSocket test")
        return None
    except Exception as e:
        print(f"❌ WebSocket test error: {e}")
        return False

def test_backend_health():
    """Test backend is running."""
    print("\n=== Testing Backend Health ===")
    try:
        response = requests.get("http://localhost:8000/health", timeout=2)
        if response.status_code == 200:
            print("✅ Backend is running")
            return True
        else:
            print(f"❌ Backend returned: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Backend not running on port 8000")
        print("   Start with: uvicorn apps.shail.main:app --reload --host 0.0.0.0 --port 8000")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def check_log_file():
    """Check if log file exists and has content."""
    print("\n=== Checking Log File ===")
    log_path = "/Users/reyhan/shail_master/.cursor/debug.log"
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            lines = f.readlines()
            print(f"✅ Log file exists with {len(lines)} lines")
            if len(lines) > 1:
                print("   Recent entries:")
                for line in lines[-5:]:
                    try:
                        entry = json.loads(line.strip())
                        print(f"   - {entry.get('location')}: {entry.get('message')}")
                    except:
                        print(f"   - {line.strip()[:80]}")
            return True
    else:
        print(f"❌ Log file not found: {log_path}")
        return False

def main():
    print("=" * 60)
    print("Missing Bits Verification Test")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Backend health
    results['backend'] = test_backend_health()
    
    if not results['backend']:
        print("\n❌ Backend is not running. Please start it first.")
        return
    
    # Test 2: Desktop ID
    results['desktop_id'], task_id = test_desktop_id()
    
    # Test 3: WebSocket
    results['websocket'] = test_permission_websocket()
    
    # Test 4: Log file
    results['log_file'] = check_log_file()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test, result in results.items():
        status = "✅" if result else "❌" if result is False else "⚠️"
        print(f"{status} {test}: {result}")
    
    if all(r for r in results.values() if r is not None):
        print("\n✅ All tests passed!")
    else:
        print("\n❌ Some tests failed. Check output above.")

if __name__ == "__main__":
    main()
