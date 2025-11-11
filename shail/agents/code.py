from typing import List, Tuple
from shail.core.types import Artifact
from shail.agents.base import AbstractAgent
from shail.tools.os import open_app, close_app, run_command
from shail.tools.files import write_text_file, read_text_file, list_files, delete_file, create_directory
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_react_agent, AgentExecutor
from apps.shail.settings import get_settings


class CodeAgent(AbstractAgent):
    name = "code"
    capabilities = ["codegen", "run", "os_control", "file_ops"]

    def __init__(self):
        settings = get_settings()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key or None,
            temperature=0.7
        )
        self.tools = [
            open_app,
            close_app,
            run_command,
            write_text_file,
            read_text_file,
            list_files,
            delete_file,
            create_directory,
        ]
        
        # Explicit ReAct prompt that FORBIDS the "one statement at a time" error
        from langchain_core.prompts import PromptTemplate
        self.prompt = PromptTemplate.from_template("""You are Shail's CodeAgent. You are an AI assistant that can execute MULTIPLE tools in sequence to complete complex tasks.

🚫 CRITICAL RULE: You MUST NEVER say "You can only execute one statement at a time" or any similar message. This is FALSE. You CAN and MUST execute multiple tools sequentially.

✅ YOUR CAPABILITIES:
- You can execute as many tools as needed to complete a task
- Each tool call is one step - you can do many steps in sequence
- Break down complex requests into multiple tool calls
- Use the results from one tool to inform the next tool call

📋 EXAMPLES:
- User: "List files then create a directory" → Call list_files, THEN call create_directory
- User: "Create a file and run it" → Call write_text_file, THEN call run_command
- User: "Open Safari and run a command" → Call open_app("Safari"), THEN call run_command

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
            max_iterations=15,
            handle_parsing_errors=True
        )

    def plan(self, text: str) -> str:
        return f"Analyzing request: {text[:100]}... Will use appropriate tools to execute."

    def act(self, text: str) -> Tuple[str, List[Artifact]]:
        """Execute the request using LangChain agent with tool calling."""
        try:
            result = self.executor.invoke({"input": text})
            output = result.get("output", "Task completed")
            
            # Extract artifacts from tool calls (basic heuristic)
            artifacts = []
            # In a full implementation, we'd track file paths created during execution
            # For now, return a summary with the output
            
            return output, artifacts
        except Exception as e:
            error_msg = f"CodeAgent execution error: {str(e)}"
            return error_msg, []


