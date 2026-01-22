"""
Test script for Detective Agent (CoAT) & Swaraj Loop
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append("/Users/reyhan/shail_master")

# Mock dependencies
sys.modules["langchain_google_genai"] = MagicMock()

from shail.agents.detective_agent import AnomalyBiasedDetective, DetectiveVerdict
from shail.orchestration.master_planner import MasterPlanner
from shail.core.types import TaskRequest

class TestDetectiveFlow(unittest.TestCase):
    
    def setUp(self):
        with patch('apps.shail.settings.get_settings') as mock_settings:
            mock_settings.return_value.gemini_model = "fake-model"
            mock_settings.return_value.gemini_api_key = "fake-key"
            
            # Setup Detective with mocked LLM
            with patch('shail.agents.detective_agent.ChatGoogleGenerativeAI') as mock_llm_cls:
                self.detective = AnomalyBiasedDetective()
                self.mock_llm_detective = mock_llm_cls.return_value
    
    def test_detective_detects_bug(self):
        """Test that detective flags bad code (simulated response)."""
        print("\n--- Testing Detective Anomaly Detection ---")
        
        # Simulate LLM response saying "Failed"
        fake_response = '{"passed": false, "anomalies": ["Infinite Loop"], "bug_narrative": "While True loop has no break.", "confidence": 0.95}'
        self.mock_llm_detective.invoke.return_value.content = fake_response
        
        verdict = self.detective.investigate("while True: pass", "Write a loop")
        
        self.assertFalse(verdict.passed)
        self.assertIn("Infinite Loop", verdict.anomalies)
        print(f"Verdict: {verdict}")

    def test_swaraj_loop_integration(self):
        """Test MasterPlanner triggers Swaraj loop."""
        print("\n--- Testing Swaraj Loop Integration ---")
        
        # We need to mock MasterPlanner's internal dependencies heavily
        with patch('shail.orchestration.master_planner.ChatGoogleGenerativeAI') as mock_mp_llm:
            with patch('shail.perception.grounding_agent.GroundingAgent.find_event') as mock_grounding:
                 with patch('shail.agents.detective_agent.AnomalyBiasedDetective.investigate') as mock_investigate:
                    
                    planner = MasterPlanner()
                    
                    # 1. Mock Grounding to find something related to "error"
                    mock_grounding.return_value = MagicMock(segment=MagicMock(story="User saw an error"), confidence=0.9)
                    
                    # 2. Mock Generation (Code Agent) response
                    mock_mp_llm.return_value.invoke.return_value.content = "print('Fixed Code')"
                    
                    # 3. Mock Verification (Detective) - Pass on first try
                    mock_investigate.return_value = DetectiveVerdict(passed=True, confidence=1.0, anomalies=[])
                    
                    # Run request
                    req = TaskRequest(text="Fix the error loop", mode="auto")
                    decision = planner.route_request(req)
                    
                    print(f"Decision: {decision}")
                    self.assertIn("Swaraj Solution Verified", decision.rationale)
                    self.assertEqual(decision.agent, "code")

if __name__ == '__main__':
    unittest.main()
