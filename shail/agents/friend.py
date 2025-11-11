"""
FriendAgent - Conversational AI assistant with desktop control capabilities.

FriendAgent is designed for hands-free computer interaction and natural conversation.
It combines conversational AI with desktop automation tools.
"""

from typing import List, Tuple
from shail.core.types import Artifact
from shail.agents.base import AbstractAgent
from shail.tools.desktop import (
    move_mouse, click_mouse, type_text, press_key, press_hotkey, scroll_mouse,
    get_mouse_position, get_screen_size, focus_window, get_window_position, list_open_windows
)
from shail.tools.os import open_app, close_app
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_react_agent, AgentExecutor
from apps.shail.settings import get_settings


class FriendAgent(AbstractAgent):
    """
    FriendAgent - Your friendly AI companion with desktop control.
    
    FriendAgent combines:
    - Natural, conversational personality
    - Desktop automation (mouse, keyboard, windows)
    - Multi-step task execution
    - Hands-free computer control
    """
    name = "friend"
    capabilities = ["desktop_control", "conversation", "automation", "hands_free"]

    def __init__(self):
        settings = get_settings()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key or None,
            temperature=0.8  # Higher temperature for more conversational, friendly responses
        )
        
        # Desktop control and OS tools
        self.tools = [
            # Mouse control
            move_mouse,
            click_mouse,
            scroll_mouse,
            get_mouse_position,
            # Keyboard control
            type_text,
            press_key,
            press_hotkey,
            # Window management
            focus_window,
            get_window_position,
            list_open_windows,
            get_screen_size,
            # App control
            open_app,
            close_app,
        ]
        
        # Explicit ReAct prompt that FORBIDS the "one statement at a time" error
        from langchain_core.prompts import PromptTemplate
        self.prompt = PromptTemplate.from_template("""You are Shail's FriendAgent - a friendly, conversational AI assistant with desktop control.

🚫 CRITICAL RULE: You MUST NEVER say "You can only execute one statement at a time" or any similar message. This is FALSE. You CAN and MUST execute multiple tools sequentially.

✅ YOUR CAPABILITIES:
- You can execute as many tools as needed to complete a task
- Each tool call is one step - you can do many steps in sequence
- Control mouse, keyboard, windows, and applications
- Break down complex desktop tasks into multiple tool calls

📋 MULTI-STEP EXAMPLES:
- "Open Safari and click search" → Call open_app("Safari"), THEN call click_mouse(x, y)
- "Move mouse and click" → Call move_mouse(x, y), THEN call click_mouse(x, y)
- "Type hello and press enter" → Call type_text("hello"), THEN call press_key("enter")

PERSONALITY: Friendly, helpful, conversational. Be enthusiastic but professional.

You have access to the following tools:

{tools}

Tool Names: {tool_names}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do. You can execute multiple tools sequentially.
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times - you can do multiple actions!)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Remember: Execute as many tools as needed. NEVER say "one statement at a time" - that is incorrect.

Question: {input}
Thought:{agent_scratchpad}""")
        
        self.agent = create_react_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            max_iterations=20,  # Allow more iterations for complex desktop automation
            handle_parsing_errors=True
        )

    def plan(self, text: str) -> str:
        return f"Analyzing request: {text[:100]}... Will help with desktop control and conversation."

    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        """Execute the request using LangChain agent with desktop tools."""
        try:
            result = self.executor.invoke({"input": text})
            output = result.get("output", "Task completed")
            
            # Extract artifacts from tool calls
            artifacts = []
            # In future, we could track window positions, mouse paths, etc.
            
            return output, artifacts
        except Exception as e:
            error_msg = f"FriendAgent execution error: {str(e)}"
            return error_msg, []
