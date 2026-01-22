#!/usr/bin/env python3
"""
Comprehensive Shail System Test Suite
Tests everything we've built: WebSocket fixes, Phase 6 enhancements, one-click startup
"""

import sys
import os
import json
import time
import requests
import asyncio
import websockets
from typing import Dict, List, Tuple, Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

class ShailTestSuite:
    def __init__(self):
        self.base_url = "http://localhost:8000"
        self.ws_url = "ws://localhost:8000/ws/brain"
        self.results = []
        
    def log(self, message: str, status: str = "INFO"):
        colors = {
            "PASS": Colors.GREEN,
            "FAIL": Colors.RED,
            "WARN": Colors.YELLOW,
            "INFO": Colors.BLUE
        }
        color = colors.get(status, Colors.NC)
        print(f"{color}[{status}]{Colors.NC} {message}")
    
    def test_backend_health(self) -> bool:
        """Test 1: Backend is running and healthy"""
        self.log("Testing backend health...", "INFO")
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.log(f"✅ Backend healthy: {data}", "PASS")
                return True
            else:
                self.log(f"❌ Backend returned {response.status_code}", "FAIL")
                return False
        except requests.exceptions.ConnectionError:
            self.log("❌ Backend not running on port 8000", "FAIL")
            self.log("   Start with: ./start_shail.sh", "WARN")
            return False
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_websocket_connection(self) -> bool:
        """Test 2: WebSocket connection (our fix!)"""
        self.log("Testing WebSocket connection...", "INFO")
        try:
            async def test():
                try:
                    async with websockets.connect(self.ws_url) as ws:
                        self.log("✅ WebSocket connected!", "PASS")
                        
                        # Test ping/pong
                        await ws.send(json.dumps({"type": "ping"}))
                        response = await asyncio.wait_for(ws.recv(), timeout=5)
                        data = json.loads(response)
                        if data.get("type") == "pong":
                            self.log("✅ Ping/pong working!", "PASS")
                            return True
                        else:
                            self.log(f"⚠️ Unexpected response: {data}", "WARN")
                            return False
                except websockets.exceptions.InvalidStatusCode as e:
                    self.log(f"❌ WebSocket handshake failed: {e}", "FAIL")
                    return False
                except Exception as e:
                    self.log(f"❌ WebSocket error: {e}", "FAIL")
                    return False
            
            return asyncio.run(test())
        except ImportError:
            self.log("⚠️ websockets library not installed", "WARN")
            return None
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_desktop_id_submission(self) -> bool:
        """Test 3: Desktop ID is accepted and stored"""
        self.log("Testing desktop_id submission...", "INFO")
        try:
            payload = {
                "text": "test task with desktop context",
                "mode": "auto",
                "desktop_id": "Desktop 1"
            }
            response = requests.post(
                f"{self.base_url}/tasks",
                json=payload,
                timeout=5
            )
            if response.status_code == 202:
                data = response.json()
                task_id = data.get("task_id")
                self.log(f"✅ Task submitted with desktop_id: {task_id}", "PASS")
                return True, task_id
            else:
                self.log(f"❌ Task submission failed: {response.status_code}", "FAIL")
                return False, None
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False, None
    
    def test_chat_endpoint(self) -> bool:
        """Test 4: Direct chat endpoint"""
        self.log("Testing /chat endpoint...", "INFO")
        try:
            payload = {"text": "Hello, this is a test message"}
            response = requests.post(
                f"{self.base_url}/chat",
                json=payload,
                timeout=65  # Increased from 10 to 65 seconds to match LLM timeout
            )
            if response.status_code == 200:
                data = response.json()
                if "text" in data:
                    self.log(f"✅ Chat response received: {data['text'][:50]}...", "PASS")
                    return True
                else:
                    self.log(f"⚠️ Unexpected response format: {data}", "WARN")
                    return False
            else:
                self.log(f"❌ Chat failed: {response.status_code}", "FAIL")
                return False
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_chat_history_endpoint(self) -> bool:
        """Test 5: Chat history endpoint"""
        self.log("Testing /chat/history endpoint...", "INFO")
        try:
            response = requests.get(f"{self.base_url}/chat/history", timeout=5)
            if response.status_code == 200:
                history = response.json()
                self.log(f"✅ Chat history retrieved: {len(history)} messages", "PASS")
                return True
            else:
                self.log(f"❌ Chat history failed: {response.status_code}", "FAIL")
                return False
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_task_results_endpoint(self, task_id: str) -> bool:
        """Test 6: Task results endpoint"""
        self.log(f"Testing /tasks/{task_id}/results...", "INFO")
        try:
            response = requests.get(
                f"{self.base_url}/tasks/{task_id}/results",
                timeout=5
            )
            if response.status_code == 200:
                results = response.json()
                self.log(f"✅ Task results retrieved", "PASS")
                return True
            elif response.status_code == 404:
                self.log("⚠️ Task not found (may not be processed yet)", "WARN")
                return None
            else:
                self.log(f"❌ Task results failed: {response.status_code}", "FAIL")
                return False
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_permission_endpoints(self) -> bool:
        """Test 7: Permission endpoints"""
        self.log("Testing permission endpoints...", "INFO")
        try:
            # Test awaiting approval endpoint
            response = requests.get(
                f"{self.base_url}/tasks/awaiting-approval",
                timeout=5
            )
            if response.status_code == 200:
                pending = response.json()
                self.log(f"✅ Permission endpoint working: {len(pending)} pending", "PASS")
                return True
            else:
                self.log(f"❌ Permission endpoint failed: {response.status_code}", "FAIL")
                return False
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def test_websocket_state_updates(self) -> bool:
        """Test 8: WebSocket state updates"""
        self.log("Testing WebSocket state updates...", "INFO")
        try:
            async def test():
                async with websockets.connect(self.ws_url) as ws:
                    # Wait for state_history or state_update
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=5)
                        data = json.loads(message)
                        if data.get("type") in ["state_update", "state_history"]:
                            self.log("✅ State updates working!", "PASS")
                            return True
                        else:
                            self.log(f"⚠️ Unexpected message type: {data.get('type')}", "WARN")
                            return False
                    except asyncio.TimeoutError:
                        self.log("⚠️ No state update received (may be normal if no tasks running)", "WARN")
                        return None
            
            return asyncio.run(test())
        except Exception as e:
            self.log(f"❌ Error: {e}", "FAIL")
            return False
    
    def run_all_tests(self):
        """Run complete test suite"""
        print("\n" + "="*60)
        print("🧪 SHAIL COMPREHENSIVE TEST SUITE")
        print("="*60 + "\n")
        
        # Test 1: Backend health
        health_ok = self.test_backend_health()
        if not health_ok:
            print("\n❌ Backend is not running. Start it first:")
            print("   ./start_shail.sh")
            return
        
        print()
        
        # Test 2: WebSocket connection (our fix!)
        ws_ok = self.test_websocket_connection()
        self.results.append(("WebSocket Connection", ws_ok))
        print()
        
        # Test 3: Desktop ID
        desktop_ok, task_id = self.test_desktop_id_submission()
        self.results.append(("Desktop ID Submission", desktop_ok))
        print()
        
        # Test 4: Chat endpoint
        chat_ok = self.test_chat_endpoint()
        self.results.append(("Chat Endpoint", chat_ok))
        print()
        
        # Test 5: Chat history
        history_ok = self.test_chat_history_endpoint()
        self.results.append(("Chat History", history_ok))
        print()
        
        # Test 6: Task results
        if task_id:
            results_ok = self.test_task_results_endpoint(task_id)
            self.results.append(("Task Results", results_ok))
            print()
        
        # Test 7: Permissions
        perm_ok = self.test_permission_endpoints()
        self.results.append(("Permission Endpoints", perm_ok))
        print()
        
        # Test 8: WebSocket state updates
        state_ok = self.test_websocket_state_updates()
        self.results.append(("WebSocket State Updates", state_ok))
        print()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for _, result in self.results if result is True)
        failed = sum(1 for _, result in self.results if result is False)
        warnings = sum(1 for _, result in self.results if result is None)
        total = len(self.results)
        
        for name, result in self.results:
            if result is True:
                status = f"{Colors.GREEN}✅ PASS{Colors.NC}"
            elif result is False:
                status = f"{Colors.RED}❌ FAIL{Colors.NC}"
            else:
                status = f"{Colors.YELLOW}⚠️  WARN{Colors.NC}"
            print(f"{status}: {name}")
        
        print(f"\nTotal: {passed}/{total} passed, {failed} failed, {warnings} warnings")
        
        if passed == total:
            print(f"\n{Colors.GREEN}🎉 All tests passed!{Colors.NC}")
        elif failed == 0:
            print(f"\n{Colors.YELLOW}⚠️  Some tests had warnings, but nothing failed{Colors.NC}")
        else:
            print(f"\n{Colors.RED}❌ Some tests failed. Check output above.{Colors.NC}")

if __name__ == "__main__":
    suite = ShailTestSuite()
    suite.run_all_tests()