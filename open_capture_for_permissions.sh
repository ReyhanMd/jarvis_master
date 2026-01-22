#!/bin/bash

# Script to open the correct CaptureService.app location for permission setup

APP_PATH="/Users/reyhan/shail_master/native/mac/CaptureService/DerivedData/CaptureService/Build/Products/Debug/CaptureService.app"

if [ ! -d "$APP_PATH" ]; then
    echo "❌ CaptureService.app not found at:"
    echo "   $APP_PATH"
    echo ""
    echo "   Please build the project in Xcode first (⌘+B)"
    exit 1
fi

echo "✅ Found CaptureService.app"
echo "📍 Location: $APP_PATH"
echo ""
echo "📋 Next steps:"
echo "   1. System Settings will open automatically"
echo "   2. Go to: Privacy & Security → Screen Recording"
echo "   3. Click the '+' button"
echo "   4. Navigate to the path above"
echo "   5. Select CaptureService.app and click 'Open'"
echo "   6. Toggle the switch ON (blue)"
echo ""
echo "   Opening Finder to the app location..."
echo ""

# Open Finder to the app location
open -R "$APP_PATH"

# Also try to open System Settings directly
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

echo "✅ Finder and System Settings opened"
echo "   Follow the steps above to grant permission"

