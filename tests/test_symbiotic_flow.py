"""
Test script for Symbiotic Controller Flow
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append("/Users/reyhan/shail_master")

# Mocking external deps that might be broken in env
sys.modules["langchain_google_genai"] = MagicMock()

from shail.orchestration.master_planner import MasterPlanner
from shail.core.types import TaskRequest

class TestSymbioticFlow(unittest.TestCase):
    
    def setUp(self):
        # We need to mock the settings and LLM to avoid real API calls
        with patch('apps.shail.settings.get_settings') as mock_settings:
            mock_settings.return_value.gemini_model = "fake-model"
            mock_settings.return_value.gemini_api_key = "fake-key"
            
            with patch('shail.orchestration.master_planner.ChatGoogleGenerativeAI') as mock_llm:
                self.planner = MasterPlanner()
                # Mock the LLM invoke to return something valid for the fallback route
                mock_llm.return_value.invoke.return_value.content = '{"agent": "code", "confidence": 0.8, "rationale": "Fallback"}'

    def test_symbiotic_error_flow(self):
        """
        Test the flow: User Query -> Grounding -> Vision (Anomaly) -> Code Agent
        """
        print("\n--- Testing Symbiotic flow for 'Fix the error' ---")
        
        # 1. User Query
        req = TaskRequest(text="Can you fix the error I saw in the terminal?", mode="auto")
        
        # 2. Execute
        # This should trigger _execute_symbiotic_loop because of "error" and "saw"
        decision = self.planner.route_request(req)
        
        print(f"Decision: {decision}")
        
        # 3. Assertions
        # The mock buffer in buffer.py has a story about a "TimeoutError"
        # The VisionAgent should find it and flag it as an anomaly
        # The MasterPlanner should then route to 'code' with high confidence
        self.assertEqual(decision.agent, "code")
        self.assertGreater(decision.confidence, 0.9)
        self.assertIn("Symbiotic Loop detected anomaly", decision.rationale)
        # Check for Traceback as text might be truncated
        self.assertIn("Traceback", decision.rationale)

    def test_grounding_search(self):
        """Test that grounding agent actually finds the event in the buffer."""
        print("\n--- Testing Grounding Agent search ---")
        # Use "runtime error" to differentiate from "python search"
        result = self.planner.grounding_agent.find_event("runtime error")
        self.assertIsNotNone(result.segment)
        self.assertIn("runtime error", result.segment.story.lower())
        print(f"Found story: {result.segment.story}")


if __name__ == '__main__':
    unittest.main()
