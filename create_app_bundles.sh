#!/bin/bash

# Helper script to create .app bundles from executables (if needed)

echo "📦 Creating .app Bundles from Executables"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

create_app_bundle() {
    local exec_path=$1
    local app_name=$2
    local bundle_id=$3
    local usage_desc=$4
    
    if [ ! -f "$exec_path" ]; then
        echo -e "${YELLOW}⚠️  Executable not found: $exec_path${NC}"
        return 1
    fi
    
    local app_dir="${exec_path%.*}.app"
    local contents_dir="$app_dir/Contents"
    local macos_dir="$contents_dir/MacOS"
    local resources_dir="$contents_dir/Resources"
    
    echo "Creating $app_name.app..."
    
    # Create directory structure
    mkdir -p "$macos_dir"
    mkdir -p "$resources_dir"
    
    # Copy executable
    cp "$exec_path" "$macos_dir/$app_name"
    chmod +x "$macos_dir/$app_name"
    
    # Create Info.plist
    cat > "$contents_dir/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>$app_name</string>
    <key>CFBundleIdentifier</key>
    <string>$bundle_id</string>
    <key>CFBundleName</key>
    <string>$app_name</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.3</string>
    <key>LSUIElement</key>
    <true/>
    $usage_desc
</dict>
</plist>
EOF
    
    echo -e "${GREEN}✅ Created $app_dir${NC}"
    echo "$app_dir"
}

# Find executables
CAPTURE_EXEC=$(find ~/Library/Developer/Xcode/DerivedData -name "CaptureService" -type f -perm +111 2>/dev/null | grep "Build/Products/Debug" | grep -v ".dSYM" | head -1)
ACCESS_EXEC=$(find ~/Library/Developer/Xcode/DerivedData -name "AccessibilityBridge" -type f -perm +111 2>/dev/null | grep "Build/Products/Debug" | grep -v ".dSYM" | head -1)

if [ -n "$CAPTURE_EXEC" ] && [ -f "$CAPTURE_EXEC" ]; then
    SCREEN_DESC='<key>NSScreenCaptureDescription</key>
    <string>Shail CaptureService needs screen recording access to capture desktop frames for AI vision processing.</string>'
    create_app_bundle "$CAPTURE_EXEC" "CaptureService" "com.shail.CaptureService" "$SCREEN_DESC"
fi

if [ -n "$ACCESS_EXEC" ] && [ -f "$ACCESS_EXEC" ]; then
    ACCESS_DESC='<key>NSAccessibilityUsageDescription</key>
    <string>Shail AccessibilityBridge needs accessibility access to monitor UI interactions and provide intelligent automation.</string>'
    create_app_bundle "$ACCESS_EXEC" "AccessibilityBridge" "com.shail.AccessibilityBridge" "$ACCESS_DESC"
fi

echo ""
echo "✅ Done! Now run ./setup_permissions.sh to set up permissions"

