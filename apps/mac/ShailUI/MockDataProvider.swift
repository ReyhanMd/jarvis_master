import Foundation

enum MockDataProvider {
    static let demoGraphState: GraphState = GraphState(from: [
        "task_description": "Demo: Analyze codebase and generate report",
        "current_step": 2,
        "status": "idle",
        "current_node": "execute_step",
        "nodes": ["master", "planner", "execute_step", "verifier"],
        "edges": [
            ["from": "master",       "to": "planner"],
            ["from": "planner",      "to": "execute_step"],
            ["from": "execute_step", "to": "verifier"],
            ["from": "verifier",     "to": "master"]
        ] as [[String: Any]],
        "plan_steps": [
            ["step_id": "step-1", "description": "Analyze repository structure",
             "step_type": "analysis", "executed": true, "success": true],
            ["step_id": "step-2", "description": "Identify key components",
             "step_type": "analysis", "executed": true, "success": true],
            ["step_id": "step-3", "description": "Generate summary report",
             "step_type": "action",   "executed": false]
        ] as [[String: Any]],
        "step_count": 3,
        "current_step_index": 2
    ])

    static let offlineReply = """
⚠️ SHAIL is offline — no backend detected.

I can't process your request right now. Here's how to get back online:

1. Click ⚡ in the menubar → "Start Services"
2. Make sure your repo path is configured (menubar → "Configure Repo Path…")
3. Get a free Gemini API key at aistudio.google.com and add it to your .env file

The Bird's Eye view on the right shows a demo of how SHAIL looks when live. \
Once connected, it displays your real agent workflow in real time.
"""

    static func errorReply(for error: Error) -> String {
        let msg = error.localizedDescription
        if msg.contains("504") || msg.contains("timeout") || msg.contains("timed out") {
            return """
⚠️ SHAIL hit a timeout — the LLM took too long to respond.

This usually means your Gemini API key has quota limits or the model is \
under heavy load. Here's what to try:

1. Get a fresh API key at aistudio.google.com (free tier works)
2. Add it to your .env file: GEMINI_API_KEY=your_new_key
3. Restart services: menubar ⚡ → "Stop Services" then "Start Services"

The Bird's Eye view on the right shows the demo workflow while you fix it.
"""
        }
        if msg.contains("API_KEY") || msg.contains("API key") || msg.contains("401") || msg.contains("400") {
            return """
⚠️ Invalid or missing Gemini API key.

The backend is running but the AI model rejected the key. Fix it in 3 steps:

1. Get a valid key at aistudio.google.com (it's free)
2. Open your .env file and set: GEMINI_API_KEY=your_key_here
3. Restart services: menubar ⚡ → "Stop Services" then "Start Services"

The Bird's Eye view on the right shows the demo workflow while you fix it.
"""
        }
        return """
⚠️ Something went wrong with SHAIL (\(msg)).

The Bird's Eye view on the right shows the demo workflow. \
To get back online, check the menubar ⚡ → "Start Services" \
and make sure your Gemini API key is set in .env.
"""
    }
}
