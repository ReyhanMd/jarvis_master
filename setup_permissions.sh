#!/bin/bash

# Setup script for macOS permissions - Updated for .app bundles

echo "🔐 Setting Up macOS Permissions"
echo "================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to find .app bundle
find_app_bundle() {
    local name=$1
    local local_path=$2
    
    # Search in DerivedData for .app bundles
    local found=$(find ~/Library/Developer/Xcode/DerivedData -name "$name.app" -type d 2>/dev/null | \
        grep "Build/Products/Debug" | \
        head -1)
    
    if [ -n "$found" ] && [ -d "$found" ]; then
        echo "$found"
        return 0
    fi
    
    # Check local DerivedData
    if [ -d "$local_path" ]; then
        echo "$local_path"
        return 0
    fi
    
    # Also check for executable inside .app
    local exec_path="$local_path/Contents/MacOS/$name"
    if [ -f "$exec_path" ]; then
        echo "$local_path"
        return 0
    fi
    
    return 1
}

# Find .app bundles
CAPTURE_APP=$(find_app_bundle "CaptureService" "/Users/reyhan/jarvis_master/native/mac/CaptureService/DerivedData/CaptureService/Build/Products/Debug/CaptureService.app")
ACCESS_APP=$(find_app_bundle "AccessibilityBridge" "/Users/reyhan/jarvis_master/native/mac/AccessibilityBridge/DerivedData/AccessibilityBridge/Build/Products/Debug/AccessibilityBridge.app")

if [ -z "$CAPTURE_APP" ] || [ ! -d "$CAPTURE_APP" ]; then
    echo -e "${YELLOW}⚠️  CaptureService.app not found.${NC}"
    echo "   Please build it first in Xcode:"
    echo "   1. Open CaptureService.xcodeproj"
    echo "   2. Press ⌘+B to build"
    echo "   3. Run this script again"
    echo ""
    echo "   Or if you have the executable, we'll help you create the .app bundle..."
    read -p "Press Enter to continue with manual setup..."
fi

if [ -z "$ACCESS_APP" ] || [ ! -d "$ACCESS_APP" ]; then
    echo -e "${YELLOW}⚠️  AccessibilityBridge.app not found.${NC}"
    echo "   Please build it first in Xcode:"
    echo "   1. Open AccessibilityBridge.xcodeproj"
    echo "   2. Press ⌘+B to build"
    echo "   3. Run this script again"
    echo ""
    echo "   Or if you have the executable, we'll help you create the .app bundle..."
    read -p "Press Enter to continue with manual setup..."
fi

if [ -n "$CAPTURE_APP" ] && [ -d "$CAPTURE_APP" ]; then
    echo -e "${GREEN}✅ Found CaptureService.app:${NC} $CAPTURE_APP"
fi

if [ -n "$ACCESS_APP" ] && [ -d "$ACCESS_APP" ]; then
    echo -e "${GREEN}✅ Found AccessibilityBridge.app:${NC} $ACCESS_APP"
fi

echo ""
echo "📋 Permission Setup Instructions"
echo "================================"
echo ""
echo "macOS requires .app bundles for permissions. The projects are now configured"
echo "to build as .app bundles. After building in Xcode, the apps will appear"
echo "in System Settings automatically when you run them."
echo ""

# Screen Recording Permission
echo ""
echo "1️⃣  Screen Recording Permission (CaptureService)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ -n "$CAPTURE_APP" ] && [ -d "$CAPTURE_APP" ]; then
    echo "✅ CaptureService.app found!"
    echo ""
    echo "Steps:"
    echo "  1. System Settings will open to Screen Recording"
    echo "  2. Run CaptureService once (from Xcode or terminal)"
    echo "  3. It should appear in the list automatically"
    echo "  4. If not, click '+' and navigate to:"
    echo "     $CAPTURE_APP"
    echo ""
    read -p "Press Enter to open System Settings for Screen Recording..."
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
else
    echo "⚠️  Build CaptureService.app first, then run this script again"
fi
echo ""

# Accessibility Permission
echo "2️⃣  Accessibility Permission (AccessibilityBridge)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ -n "$ACCESS_APP" ] && [ -d "$ACCESS_APP" ]; then
    echo "✅ AccessibilityBridge.app found!"
    echo ""
    echo "Steps:"
    echo "  1. System Settings will open to Accessibility"
    echo "  2. Run AccessibilityBridge once (from Xcode or terminal)"
    echo "  3. It should appear in the list automatically"
    echo "  4. If not, click '+' and navigate to:"
    echo "     $ACCESS_APP"
    echo ""
    read -p "Press Enter to open System Settings for Accessibility..."
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
else
    echo "⚠️  Build AccessibilityBridge.app first, then run this script again"
fi
echo ""

echo -e "${GREEN}✅ Permission setup complete!${NC}"
echo ""
echo "After enabling permissions:"
echo "  1. Restart the services: ./run_native_services.sh"
echo "  2. Verify they're working: ./check_native_health.sh"
echo ""
echo "💡 Tip: After building as .app bundles, macOS will automatically"
echo "   show permission dialogs when you run the apps!"
