#!/usr/bin/env python3
import sys
import json
import struct
import subprocess
import os

def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        sys.exit(0)
    msg_length = struct.unpack('@I', raw_length)[0]
    message = sys.stdin.buffer.read(msg_length).decode('utf-8')
    return json.loads(message)

def send_message(message_content):
    encoded_content = json.dumps(message_content).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('@I', len(encoded_content)))
    sys.stdout.buffer.write(encoded_content)
    sys.stdout.buffer.flush()

def main():
    while True:
        try:
            message = read_message()
            if message.get("action") == "start_backend":
                workspace_dir = "/Users/reyhan/shail workspace /shail_master/jarvis_master"
                # Run detached
                subprocess.Popen(
                    ["./start_shail.sh"], 
                    cwd=workspace_dir, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
                send_message({"status": "success", "message": "Backend start initiated"})
            else:
                send_message({"status": "error", "message": "Unknown action"})
        except Exception as e:
            send_message({"status": "error", "message": str(e)})

if __name__ == '__main__':
    main()
