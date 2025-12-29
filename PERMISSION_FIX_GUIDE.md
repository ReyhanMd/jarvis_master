# 🔧 Permission Fix Guide

## Problem Identified

1. **Projects were built as command-line tools** (`com.apple.product-type.tool`)
   - These create raw executables, not `.app` bundles
   - macOS TCC (permission system) requires `.app` bundles to show in permission dialogs

2. **CaptureService not opening in Xcode**
   - Script issue fixed

## ✅ Solution Applied

### 1. Changed Product Type to Application

Both projects now build as **macOS applications** (`.app` bundles):
- `com.apple.product-type.application` instead of `com.apple.product-type.tool`
- This creates proper `.app` bundles that macOS recognizes

### 2. Fixed Open Script

`open_xcode_projects.sh` now:
- Uses `open -a Xcode` to ensure separate windows
- Waits longer between opens
- Verifies projects exist before opening

## 📋 Steps to Fix Permissions

### Step 1: Rebuild Projects in Xcode

**IMPORTANT:** You must rebuild after the product type change!

1. **Open projects:**
   ```bash
   ./open_xcode_projects.sh
   ```

2. **In each Xcode window:**
   - Press `⌘ + Shift + K` (Clean Build Folder)
   - Press `⌘ + B` (Build)
   - Verify build succeeds

3. **The output will now be:**
   - `CaptureService.app` (not `CaptureService`)
   - `AccessibilityBridge.app` (not `AccessibilityBridge`)

### Step 2: Run Apps Once

After building, run each app once to trigger permission dialogs:

**Option A: Run from Xcode**
- Press `⌘ + R` in each project
- macOS will show permission dialogs
- Click "Open System Settings"
- Enable checkboxes

**Option B: Run from Terminal**
```bash
# Find the .app bundles
find ~/Library/Developer/Xcode/DerivedData -name "CaptureService.app" -type d | grep Debug | head -1
find ~/Library/Developer/Xcode/DerivedData -name "AccessibilityBridge.app" -type d | grep Debug | head -1

# Run them
open "/path/to/CaptureService.app"
open "/path/to/AccessibilityBridge.app"
```

### Step 3: Grant Permissions

When you run the apps:
1. **macOS will show permission dialogs automatically**
2. Click "Open System Settings"
3. The apps will appear in the permission lists
4. Enable the checkboxes
5. Restart the apps

### Step 4: Verify

```bash
./check_native_health.sh
```

## 🔍 Finding the .app Bundles

After rebuilding, the apps will be at:

```bash
# CaptureService.app
~/Library/Developer/Xcode/DerivedData/CaptureService-*/Build/Products/Debug/CaptureService.app

# AccessibilityBridge.app  
~/Library/Developer/Xcode/DerivedData/AccessibilityBridge-*/Build/Products/Debug/AccessibilityBridge.app
```

## 🆘 If Apps Still Don't Appear

If after rebuilding as `.app` bundles they still don't appear:

### Option 1: Use the File Picker (What you're doing now)

1. In System Settings → Privacy & Security → Screen Recording
2. Click the `+` button
3. Navigate to: `~/Library/Developer/Xcode/DerivedData/`
4. Find: `CaptureService-*/Build/Products/Debug/CaptureService.app`
5. Select the **.app folder** (not the executable inside)
6. Click "Open"

### Option 2: Create App Bundles Manually

```bash
./create_app_bundles.sh
```

This script will:
- Find the executables
- Create proper `.app` bundles around them
- Add Info.plist with permission descriptions
- Make them ready for permission dialogs

### Option 3: Use tccutil (Advanced)

```bash
# Reset permissions (if needed)
tccutil reset ScreenCapture com.shail.CaptureService
tccutil reset Accessibility com.shail.AccessibilityBridge

# Then run the apps again
```

## ✅ What Changed

### Before:
- Product type: `com.apple.product-type.tool`
- Output: Raw executable (`CaptureService`)
- Permission dialog: ❌ Doesn't appear automatically

### After:
- Product type: `com.apple.product-type.application`
- Output: App bundle (`CaptureService.app`)
- Permission dialog: ✅ Appears automatically when run

## 🎯 Next Steps

1. **Rebuild both projects** in Xcode (⌘+B)
2. **Run each app once** (⌘+R in Xcode)
3. **Grant permissions** when dialogs appear
4. **Test services:**
   ```bash
   ./run_native_services.sh
   ./check_native_health.sh
   ```

## 📝 Notes

- The `.app` bundles contain the executable in `Contents/MacOS/`
- Info.plist files already have permission descriptions
- After first run, apps will appear in System Settings automatically
- You can also manually add them via the `+` button if needed

