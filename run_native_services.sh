#!/bin/bash

# Run native services directly from terminal with proper cleanup and port management

set -e  # Exit on error

echo "🚀 Running Native Services from Terminal"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to kill existing processes
cleanup_processes() {
    echo "🧹 Cleaning up existing processes..."
    
    # Kill CaptureService processes
    if pgrep -f "CaptureService" > /dev/null; then
        echo "   Killing existing CaptureService processes..."
        pkill -9 -f "CaptureService" 2>/dev/null || true
        sleep 1
    fi
    
    # Kill AccessibilityBridge processes
    if pgrep -f "AccessibilityBridge" > /dev/null; then
        echo "   Killing existing AccessibilityBridge processes..."
        pkill -9 -f "AccessibilityBridge" 2>/dev/null || true
        sleep 1
    fi
    
    echo "✅ Cleanup complete"
}

# Function to check and free ports
check_ports() {
    local port=$1
    local service_name=$2
    
    echo "🔍 Checking port $port for $service_name..."
    
    # Check if port is in use
    if lsof -ti:$port > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Port $port is already in use${NC}"
        echo "   Finding and killing process using port $port..."
        
        # Get PID using the port
        local pid=$(lsof -ti:$port)
        if [ -n "$pid" ]; then
            echo "   Killing process $pid..."
            kill -9 $pid 2>/dev/null || true
            sleep 1
        fi
        
        # Verify port is free
        if lsof -ti:$port > /dev/null 2>&1; then
            echo -e "${RED}❌ Failed to free port $port${NC}"
            return 1
        else
            echo -e "${GREEN}✅ Port $port is now free${NC}"
        fi
    else
        echo -e "${GREEN}✅ Port $port is available${NC}"
    fi
    
    return 0
}

# Function to find executable with multiple search strategies
# Now supports both .app bundles (preferred) and raw executables (fallback)
find_executable() {
    local name=$1
    local local_path=$2
    
    # Strategy 1: Search for .app bundle first (preferred - for permissions)
    local app_found=$(find ~/Library/Developer/Xcode/DerivedData -name "$name.app" -type d 2>/dev/null | \
        grep "Build/Products/Debug" | \
        head -1)
    
    if [ -n "$app_found" ] && [ -d "$app_found" ]; then
        # Return the executable inside the .app bundle
        local exec_path="$app_found/Contents/MacOS/$name"
        if [ -f "$exec_path" ] && [ -x "$exec_path" ]; then
            echo "$exec_path"
            return 0
        fi
    fi
    
    # Strategy 2: Search for raw executable (fallback for old builds)
    local found=$(find ~/Library/Developer/Xcode/DerivedData -name "$name" -type f -perm +111 2>/dev/null | \
        grep "Build/Products/Debug" | \
        grep -v ".dSYM" | \
        head -1)
    
    if [ -n "$found" ] && [ -f "$found" ]; then
        echo "$found"
        return 0
    fi
    
    # Strategy 3: Check local DerivedData (.app bundle)
    local local_app_path="${local_path}.app"
    if [ -d "$local_app_path" ]; then
        local exec_path="$local_app_path/Contents/MacOS/$name"
        if [ -f "$exec_path" ] && [ -x "$exec_path" ]; then
            echo "$exec_path"
            return 0
        fi
    fi
    
    # Strategy 4: Check local DerivedData (raw executable)
    if [ -f "$local_path" ]; then
        echo "$local_path"
        return 0
    fi
    
    # Strategy 5: Search more broadly for raw executable
    found=$(find ~/Library/Developer/Xcode/DerivedData -name "$name" -type f -perm +111 2>/dev/null | \
        grep -v ".dSYM" | \
        head -1)
    
    if [ -n "$found" ] && [ -f "$found" ]; then
        echo "$found"
        return 0
    fi
    
    return 1
}

# Cleanup existing processes
cleanup_processes

# Check and free ports
check_ports 8765 "CaptureService" || exit 1
check_ports 8766 "AccessibilityBridge" || exit 1

echo ""

# Find executables with proper path resolution
echo "🔍 Finding executables..."

CAPTURE_EXEC=$(find_executable "CaptureService" "/Users/reyhan/shail_master/native/mac/CaptureService/DerivedData/CaptureService/Build/Products/Debug/CaptureService")
ACCESS_EXEC=$(find_executable "AccessibilityBridge" "/Users/reyhan/shail_master/native/mac/AccessibilityBridge/DerivedData/AccessibilityBridge/Build/Products/Debug/AccessibilityBridge")

# Verify CaptureService
if [ -z "$CAPTURE_EXEC" ] || [ ! -f "$CAPTURE_EXEC" ]; then
    echo -e "${RED}❌ CaptureService not found${NC}"
    echo "   Please build in Xcode first:"
    echo "   1. Open CaptureService.xcodeproj"
    echo "   2. Press ⌘+B to build"
    echo "   3. Run this script again"
    exit 1
fi

# Verify AccessibilityBridge
if [ -z "$ACCESS_EXEC" ] || [ ! -f "$ACCESS_EXEC" ]; then
    echo -e "${RED}❌ AccessibilityBridge not found${NC}"
    echo "   Please build in Xcode first:"
    echo "   1. Open AccessibilityBridge.xcodeproj"
    echo "   2. Press ⌘+B to build"
    echo "   3. Run this script again"
    exit 1
fi

echo -e "${GREEN}✅ Found CaptureService:${NC} $CAPTURE_EXEC"
echo -e "${GREEN}✅ Found AccessibilityBridge:${NC} $ACCESS_EXEC"
echo ""

# Make executables executable (just in case)
chmod +x "$CAPTURE_EXEC" 2>/dev/null || true
chmod +x "$ACCESS_EXEC" 2>/dev/null || true

echo "🚀 Starting services in separate Terminal windows..."
echo ""

# Create a temporary script for CaptureService to avoid path issues
CAPTURE_SCRIPT=$(mktemp /tmp/capture_service_XXXXXX.sh)
cat > "$CAPTURE_SCRIPT" << EOF
#!/bin/bash
cd /Users/reyhan/shail_master
echo "🎥 CaptureService"
echo "=================="
echo "Path: $CAPTURE_EXEC"
echo ""
exec "$CAPTURE_EXEC"
EOF
chmod +x "$CAPTURE_SCRIPT"

# Create a temporary script for AccessibilityBridge
ACCESS_SCRIPT=$(mktemp /tmp/accessibility_bridge_XXXXXX.sh)
cat > "$ACCESS_SCRIPT" << EOF
#!/bin/bash
cd /Users/reyhan/shail_master
echo "♿ AccessibilityBridge"
echo "======================"
echo "Path: $ACCESS_EXEC"
echo ""
exec "$ACCESS_EXEC"
EOF
chmod +x "$ACCESS_SCRIPT"

# Launch CaptureService in new Terminal window
echo "🎥 Starting CaptureService..."
osascript << EOF
tell application "Terminal"
    activate
    do script "$CAPTURE_SCRIPT"
end tell
EOF

sleep 2

# Launch AccessibilityBridge in new Terminal window
echo "♿ Starting AccessibilityBridge..."
osascript << EOF
tell application "Terminal"
    activate
    do script "$ACCESS_SCRIPT"
end tell
EOF

echo ""
echo -e "${GREEN}✅ Both services launched in separate Terminal windows${NC}"
echo ""
echo "📋 What to expect:"
echo "   1. Permission popups will appear"
echo "   2. Click 'Open System Settings'"
echo "   3. Enable the checkboxes for:"
echo "      - CaptureService (Screen Recording)"
echo "      - AccessibilityBridge (Accessibility)"
echo "   4. Services will automatically continue after permissions granted"
echo ""
echo "📊 Check the Terminal windows for output!"
echo "🛑 To stop: Run ./stop_native_services.sh or close Terminal windows"
echo ""
echo "💡 Temporary scripts created:"
echo "   $CAPTURE_SCRIPT"
echo "   $ACCESS_SCRIPT"
echo "   (These will be cleaned up when services stop)"
