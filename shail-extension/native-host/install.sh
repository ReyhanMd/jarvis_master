#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
HOST_NAME="com.shail.native_host"
TARGET_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"

mkdir -p "$TARGET_DIR"

# NOTE: You will need to replace <YOUR_EXTENSION_ID> with the actual ID from chrome://extensions/
cat > "$TARGET_DIR/$HOST_NAME.json" << EOF
{
  "name": "com.shail.native_host",
  "description": "Shail Native Host for Backend Control",
  "path": "$DIR/host.py",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://<hjpjpgklahpdmhpepdhoefpfckfoknaa>/"
  ]
}
EOF

chmod +x "$DIR/host.py"
echo "Native host manifest installed to $TARGET_DIR/$HOST_NAME.json"
echo "Please edit the file and replace <hjpjpgklahpdmhpepdhoefpfckfoknaa> with your extension ID."
