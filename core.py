from mlx_lm import load, generate
import os
import subprocess

print("Loading Jarvis's brain (Gemma 2 9B)...")
model, tokenizer = load("mlx-community/gemma-2-9b-it-4bit")
print("Brain loaded. Jarvis is online.")

def open_app(app_name: str) -> str:
    try:
        subprocess.run(["open", "-a", app_name], check=True)
        return f"Successfully opened {app_name}."
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        return f"Error: Could not open {app_name}. Is it installed?"

print("\n--- Jarvis Prototype v0.1 ---")
print("You can now talk to Jarvis. Type 'quit' to exit.")

while True:
    user_input = input("\n[You]: ")

    if user_input.lower() == 'quit':
        break

    if "open" in user_input.lower() and not "don't open" in user_input.lower():
        try:
            app_to_open = user_input.lower().split("open ")[1].strip()
            tool_response = open_app(app_to_open)
            print(f"[Jarvis]: {tool_response}")
            continue
        except IndexError:
            pass

    messages = [{"role": "user", "content": user_input}]
    full_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    # Note: We have removed the 'temp' argument from this line
    response = generate(model, tokenizer, prompt=full_prompt, verbose=False, max_tokens=150)

    print(f"[Jarvis]: {response}")