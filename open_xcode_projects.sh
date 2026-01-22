#!/bin/bash

# Quick script to open both Xcode projects

echo "🚀 Opening Xcode Projects..."
echo ""

CAPTURE_PROJECT="/Users/reyhan/shail_master/native/mac/CaptureService/CaptureService.xcodeproj"
ACCESS_PROJECT="/Users/reyhan/shail_master/native/mac/AccessibilityBridge/AccessibilityBridge.xcodeproj"

# Verify projects exist
if [ ! -d "$CAPTURE_PROJECT" ]; then
    echo "❌ Error: CaptureService project not found at $CAPTURE_PROJECT"
    exit 1
fi

if [ ! -d "$ACCESS_PROJECT" ]; then
    echo "❌ Error: AccessibilityBridge project not found at $ACCESS_PROJECT"
    exit 1
fi

# Open CaptureService in new Xcode window
echo "📦 Opening CaptureService..."
open -a Xcode "$CAPTURE_PROJECT"

# Wait a bit longer to ensure first window opens
sleep 3

# Open AccessibilityBridge in new Xcode window
echo "📦 Opening AccessibilityBridge..."
open -a Xcode "$ACCESS_PROJECT"

echo ""
echo "✅ Both Xcode projects opened!"
echo ""
echo "📋 Next Steps:"
echo "   1. In CaptureService project: Press ⌘+B to build, then ⌘+R to run"
echo "   2. In AccessibilityBridge project: Press ⌘+B to build, then ⌘+R to run"
echo "   3. Grant permissions when prompted (apps will now appear in permission lists!)"
echo "   4. After permissions granted, run: ./run_native_services.sh"
echo ""
echo "💡 Note: Projects are now configured as .app bundles for proper permission handling"
echo "📖 See BUILD_NATIVE_SERVICES.md for detailed instructions"

