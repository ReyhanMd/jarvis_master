from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_community.llms import MLXLM
from tools.computer_tools import open_app, close_app

# --- 1. The Brain (LLM) ---
print("🧠 Loading Jarvis's brain (Gemma 2 9B on MLX)...")
llm = MLXLM(model_id="mlx-community/gemma-2-9b-it-4bit")
print("✅ Brain loaded.")

# --- 2. The Tools (Motor Cortex) ---
tools = [open_app, close_app]

# --- 3. The Prompt (MCP) ---
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a helpful assistant named Jarvis, created by Reyhan. You have access to tools to interact with the computer. You must use the tools when a user's request requires it."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

# --- 4. The Agent ---
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# --- 5. The Main Loop ---
print("\n--- Jarvis Prototype v0.2 ---")
print("You can now talk to Jarvis. Type 'quit' to exit.")

while True:
    user_input = input("\n[You]: ")
    if user_input.lower() == 'quit':
        break

    result = agent_executor.invoke({"input": user_input})
    print(f"[Jarvis]: {result['output']}")