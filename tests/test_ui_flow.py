import unittest
from fastapi.testclient import TestClient
from apps.shail.api.server import app

class TestWorkflowState(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_workflow_state_endpoint(self):
        response = self.client.get("/workflow_state")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify structure matches Bird's Eye expectations
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        
        # Check for Master node
        master_node = next((n for n in data["nodes"] if n["id"] == "master"), None)
        self.assertIsNotNone(master_node)
        self.assertEqual(master_node["name"], "Gemini 3 Pro")
        
        # Check for Sub node
        sub_node = next((n for n in data["nodes"] if n["id"] == "sub1"), None)
        self.assertIsNotNone(sub_node)
        self.assertEqual(sub_node["type"], "Sub")
        
        print("\nVerified /workflow_state returns valid graph data.")

if __name__ == "__main__":
    unittest.main()
