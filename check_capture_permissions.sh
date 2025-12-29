#!/bin/bash

# Script to check CaptureService permissions status

echo "🔍 Checking CaptureService Permission Status..."
echo ""

# Find CaptureService.app - check both global and local DerivedData
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -name "CaptureService.app" -type d 2>/dev/null | head -1)

# Also check local DerivedData in project directory
if [ -z "$APP_PATH" ]; then
    LOCAL_PATH=$(find . -path "*/DerivedData/*/Build/Products/Debug/CaptureService.app" -type d 2>/dev/null | head -1)
    if [ -n "$LOCAL_PATH" ]; then
        APP_PATH=$(realpath "$LOCAL_PATH" 2>/dev/null || echo "$LOCAL_PATH")
    fi
fi

if [ -z "$APP_PATH" ]; then
    echo "❌ CaptureService.app not found"
    echo "   Searched in:"
    echo "   - ~/Library/Developer/Xcode/DerivedData"
    echo "   - ./native/mac/CaptureService/DerivedData"
    echo ""
    echo "   Make sure you've built the project in Xcode first"
    exit 1
fi

echo "✅ Found CaptureService.app at:"
echo "   $APP_PATH"
echo ""

# Check if app is running
if pgrep -f "CaptureService" > /dev/null; then
    echo "⚠️  CaptureService is currently RUNNING"
    echo "   macOS may not recognize permission changes while app is running"
    echo "   Solution: Stop the app (⌘+Q in Xcode) and restart it"
    echo ""
else
    echo "✅ CaptureService is not running (good for permission changes)"
    echo ""
fi

# Check bundle identifier
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP_PATH/Contents/Info.plist" 2>/dev/null)
echo "📦 Bundle Identifier: $BUNDLE_ID"
echo ""

# Instructions
echo "📋 PERMISSION TROUBLESHOOTING:"
echo ""
echo "1. Open System Settings → Privacy & Security → Screen Recording"
echo "2. Look for 'CaptureService' in the list"
echo "3. If it's there but OFF: Toggle it ON (blue)"
echo "4. If it's NOT in the list:"
echo "   a. Click the '+' button"
echo "   b. Navigate to: $APP_PATH"
echo "   c. Select CaptureService.app and click 'Open'"
echo "   d. Toggle it ON"
echo ""
echo "5. IMPORTANT: After enabling permission:"
echo "   - Stop CaptureService completely (⌘+Q in Xcode)"
echo "   - Wait 2-3 seconds"
echo "   - Rebuild and run again"
echo ""
echo "6. The app will now retry permission checks automatically"
echo ""

