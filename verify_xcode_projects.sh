#!/bin/bash

# Verify Xcode projects are correctly configured

echo "🔍 Verifying Xcode Projects..."
echo ""

# Check CaptureService
echo "📦 Checking CaptureService project..."
cd /Users/reyhan/shail_master/native/mac/CaptureService

# Check if all Swift files exist
files=("main.swift" "ScreenCaptureService.swift" "WebSocketServer.swift" "PermissionManager.swift")
missing=0

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file exists"
    else
        echo "  ❌ $file MISSING"
        missing=1
    fi
done

if [ $missing -eq 0 ]; then
    echo "  ✅ All Swift files present"
else
    echo "  ❌ Some files are missing!"
fi

# Check project file references
if grep -q "main.swift in Sources" CaptureService.xcodeproj/project.pbxproj; then
    echo "  ✅ main.swift in Sources build phase"
else
    echo "  ❌ main.swift NOT in Sources build phase"
fi

if grep -q "ScreenCaptureService.swift in Sources" CaptureService.xcodeproj/project.pbxproj; then
    echo "  ✅ ScreenCaptureService.swift in Sources build phase"
else
    echo "  ❌ ScreenCaptureService.swift NOT in Sources build phase"
fi

if grep -q "WebSocketServer.swift in Sources" CaptureService.xcodeproj/project.pbxproj; then
    echo "  ✅ WebSocketServer.swift in Sources build phase"
else
    echo "  ❌ WebSocketServer.swift NOT in Sources build phase"
fi

if grep -q "PermissionManager.swift in Sources" CaptureService.xcodeproj/project.pbxproj; then
    echo "  ✅ PermissionManager.swift in Sources build phase"
else
    echo "  ❌ PermissionManager.swift NOT in Sources build phase"
fi

echo ""

# Check AccessibilityBridge
echo "📦 Checking AccessibilityBridge project..."
cd /Users/reyhan/shail_master/native/mac/AccessibilityBridge

files=("main.swift" "AccessibilityBridge.swift" "AXWebSocketServer.swift" "AXPermissionManager.swift")
missing=0

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file exists"
    else
        echo "  ❌ $file MISSING"
        missing=1
    fi
done

if [ $missing -eq 0 ]; then
    echo "  ✅ All Swift files present"
else
    echo "  ❌ Some files are missing!"
fi

# Check project file references
if grep -q "main.swift in Sources" AccessibilityBridge.xcodeproj/project.pbxproj; then
    echo "  ✅ main.swift in Sources build phase"
else
    echo "  ❌ main.swift NOT in Sources build phase"
fi

if grep -q "AccessibilityBridge.swift in Sources" AccessibilityBridge.xcodeproj/project.pbxproj; then
    echo "  ✅ AccessibilityBridge.swift in Sources build phase"
else
    echo "  ❌ AccessibilityBridge.swift NOT in Sources build phase"
fi

if grep -q "AXWebSocketServer.swift in Sources" AccessibilityBridge.xcodeproj/project.pbxproj; then
    echo "  ✅ AXWebSocketServer.swift in Sources build phase"
else
    echo "  ❌ AXWebSocketServer.swift NOT in Sources build phase"
fi

if grep -q "AXPermissionManager.swift in Sources" AccessibilityBridge.xcodeproj/project.pbxproj; then
    echo "  ✅ AXPermissionManager.swift in Sources build phase"
else
    echo "  ❌ AXPermissionManager.swift NOT in Sources build phase"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Verification complete!"
echo ""
echo "If all checks passed, you can now:"
echo "  1. Open projects: ./open_xcode_projects.sh"
echo "  2. Build & Run: ⌘+R in Xcode"
echo "  3. Grant permissions when prompted"

