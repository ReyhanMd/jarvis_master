import os
import subprocess
import sys
import logging
from fuzzywuzzy import process
import asyncio

try:
    import pygetwindow as gw
except ImportError:
    gw = None

from langchain.tools import tool

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def focus_window(title_keyword: str) -> bool:
    if not gw:
        logger.warning("pygetwindow is not available on this system.")
        return False

    await asyncio.sleep(1.5)
    title_keyword = title_keyword.lower().strip()

    for window in gw.getAllWindows():
        if title_keyword in window.title.lower():
            if window.isMinimized:
                window.restore()
            window.activate()
            logger.info(f"Window focused: {window.title}")
            return True
    logger.warning("Window not found for focusing.")
    return False

async def index_files(base_dirs):
    file_index = []
    for base_dir in base_dirs:
        for root, _, files in os.walk(base_dir):
            for f in files:
                file_index.append({
                    "name": f,
                    "path": os.path.join(root, f),
                    "type": "file"
                })
    logger.info(f"Indexed {len(file_index)} files from {base_dirs}.")
    return file_index

async def search_file(query, index):
    choices = [item["name"] for item in index]
    if not choices:
        logger.warning("No files to match against.")
        return None

    best_match, score = process.extractOne(query, choices)
    logger.info(f"Matched '{query}' to '{best_match}' (Score: {score})")
    if score > 70:
        for item in index:
            if item["name"] == best_match:
                return item
    return None

async def open_file(item):
    try:
        logger.info(f"Opening file: {item['path']}")
        if sys.platform == 'darwin': # macOS
            subprocess.call(['open', item["path"]])
        elif os.name == 'nt': # Windows
            os.startfile(item["path"])
        else: # Linux
            subprocess.call(['xdg-open', item["path"]])
        await focus_window(item["name"])
        return f"File opened: {item['name']}"
    except Exception as e:
        logger.error(f"Error opening file: {e}")
        return f"Failed to open file. {e}"

async def handle_command(command, index):
    item = await search_file(command, index)
    if item:
        return await open_file(item)
    else:
        logger.warning("File not found.")
        return "File not found."

@tool
async def Play_file(name: str) -> str:
    """
    Searches for and opens a file by name from the user's Documents folder.
    """
    # CORRECTED SECTION FOR MACOS
    home_dir = os.path.expanduser("~")
    folders_to_index = [os.path.join(home_dir, "Documents")]

    index = await index_files(folders_to_index)
    command = name.strip()
    return await handle_command(command, index)