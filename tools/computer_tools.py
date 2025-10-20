import subprocess
from langchain_core.tools import tool

@tool
def open_app(app_name: str) -> str:
    """
    Opens a desktop application on macOS given its name.
    Use this to launch applications like 'Calculator', 'TextEdit', or 'Safari'.
    Example: 'open Calculator'
    """
    try:
        # The capture_output and text=True arguments are added for better error handling
        result = subprocess.run(["open", "-a", app_name], check=True, capture_output=True, text=True)
        return f"Successfully opened {app_name}."
    except subprocess.CalledProcessError as e:
        # This provides a more detailed error message if the app can't be found
        return f"Error: Could not open '{app_name}'. It might not be installed or the name is incorrect. Details: {e.stderr}"

# We can add more tools from Gaurav's repo here later (file control, etc.)a