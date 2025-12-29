#!/bin/bash

# Shail Native Services Startup Script
# Starts all native and Python services in the correct order

set -e

echo "🚀 Starting Shail Native Services & AI Orchestration"
echo "=================================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check platform
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macOS"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    PLATFORM="Windows"
else
    echo -e "${RED}❌ Unsupported platform: $OSTYPE${NC}"
    exit 1
fi

echo -e "${GREEN}📍 Platform: $PLATFORM${NC}"
echo ""

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Function to wait for service
wait_for_service() {
    local service=$1
    local port=$2
    local max_wait=30
    local waited=0
    
    echo -n "⏳ Waiting for $service on port $port..."
    
    while ! check_port $port && [ $waited -lt $max_wait ]; do
        sleep 1
        waited=$((waited + 1))
        echo -n "."
    done
    
    if check_port $port; then
        echo -e " ${GREEN}✓${NC}"
        return 0
    else
        echo -e " ${RED}✗ (timeout)${NC}"
        return 1
    fi
}

# ===============================
# 1. Start Native Services
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Starting Native Services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$PLATFORM" == "macOS" ]; then
    # Check if native services are built
    CAPTURE_BIN="native/mac/CaptureService/build/Release/CaptureService"
    ACCESS_BIN="native/mac/AccessibilityBridge/build/Release/AccessibilityBridge"
    
    # Try to build CaptureService if not exists
    if [ ! -f "$CAPTURE_BIN" ]; then
        echo -e "${YELLOW}⚠️  CaptureService not built. Attempting to build...${NC}"
        cd native/mac/CaptureService
        if xcodebuild -project CaptureService.xcodeproj -scheme CaptureService -configuration Release > /dev/null 2>&1; then
            echo -e "${GREEN}✓ CaptureService built successfully${NC}"
        else
            echo -e "${YELLOW}⚠️  Failed to build CaptureService (Xcode required)${NC}"
            echo "   Install Xcode from App Store, then run: sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer"
            echo "   For now, continuing without native services..."
            CAPTURE_BIN=""  # Mark as unavailable
        fi
        cd ../../..
    fi
    
    # Try to build AccessibilityBridge if not exists
    if [ ! -f "$ACCESS_BIN" ]; then
        echo -e "${YELLOW}⚠️  AccessibilityBridge not built. Attempting to build...${NC}"
        cd native/mac/AccessibilityBridge
        if xcodebuild -project AccessibilityBridge.xcodeproj -scheme AccessibilityBridge -configuration Release > /dev/null 2>&1; then
            echo -e "${GREEN}✓ AccessibilityBridge built successfully${NC}"
        else
            echo -e "${YELLOW}⚠️  Failed to build AccessibilityBridge (Xcode required)${NC}"
            echo "   Install Xcode from App Store, then run: sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer"
            echo "   For now, continuing without native services..."
            ACCESS_BIN=""  # Mark as unavailable
        fi
        cd ../../..
    fi
    
    # Start CaptureService only if built successfully
    if [ -f "$CAPTURE_BIN" ]; then
        echo "🎥 Starting CaptureService..."
        ./$CAPTURE_BIN > logs/capture_service.log 2>&1 &
        CAPTURE_PID=$!
        echo "   PID: $CAPTURE_PID"
        sleep 2
    else
        echo -e "${YELLOW}⚠️  CaptureService not available (Xcode required)${NC}"
        CAPTURE_PID=""
    fi
    
    # Start AccessibilityBridge only if built successfully
    if [ -f "$ACCESS_BIN" ]; then
        echo "♿ Starting AccessibilityBridge..."
        ./$ACCESS_BIN > logs/accessibility_bridge.log 2>&1 &
        ACCESS_PID=$!
        echo "   PID: $ACCESS_PID"
        sleep 2
    else
        echo -e "${YELLOW}⚠️  AccessibilityBridge not available (Xcode required)${NC}"
        ACCESS_PID=""
    fi
    
else
    echo -e "${YELLOW}⚠️  Windows native services not yet implemented${NC}"
    echo "   See native/win/ for C# code structure"
    CAPTURE_PID=""
    ACCESS_PID=""
fi

echo ""

# ===============================
# 2. Start Python Services
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Starting Python Services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check for virtual environment
if [ ! -d "services_env" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating...${NC}"
    python3 -m venv services_env
fi

# Activate virtual environment
source services_env/bin/activate

# Create logs directory
mkdir -p logs

# Upgrade pip first
echo "📦 Upgrading pip..."
pip install -q --upgrade pip

# Install dependencies if needed
echo "📦 Checking Python dependencies..."
for service in ui_twin action_executor vision rag_retriever planner; do
    if [ ! -f "services/$service/.installed" ]; then
        echo "   Installing $service dependencies..."
        cd services/$service
        pip install -q -r requirements.txt
        touch .installed
        cd ../..
    fi
done
echo -e "${GREEN}✓ Dependencies ready${NC}"
echo ""

# Start UI Twin
echo "🎭 Starting UI Twin Service..."
cd services/ui_twin
python service.py > ../../logs/ui_twin.log 2>&1 &
UI_TWIN_PID=$!
cd ../..
echo "   PID: $UI_TWIN_PID"
sleep 2

# Start Action Executor
echo "🎮 Starting Action Executor Service..."
cd services/action_executor
python service.py > ../../logs/action_executor.log 2>&1 &
EXECUTOR_PID=$!
cd ../..
echo "   PID: $EXECUTOR_PID"
wait_for_service "Action Executor" 8080

# Start Vision
echo "👁️  Starting Vision Service..."
cd services/vision
python service.py > ../../logs/vision.log 2>&1 &
VISION_PID=$!
cd ../..
echo "   PID: $VISION_PID"
wait_for_service "Vision" 8081

# Start RAG Retriever
echo "🗄️  Starting RAG Retriever Service..."
cd services/rag_retriever
python service.py > ../../logs/rag_retriever.log 2>&1 &
RAG_PID=$!
cd ../..
echo "   PID: $RAG_PID"
wait_for_service "RAG Retriever" 8082

# Start Planner
echo "📋 Starting Planner Service..."
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  OPENAI_API_KEY not set. LLM features will be limited.${NC}"
fi
cd services/planner
python service.py > ../../logs/planner.log 2>&1 &
PLANNER_PID=$!
cd ../..
echo "   PID: $PLANNER_PID"
wait_for_service "Planner" 8083

echo ""

# ===============================
# 3. Summary
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All Services Started"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Service Endpoints:"
echo "   • CaptureService:      ws://localhost:8765/capture"
echo "   • AccessibilityBridge: ws://localhost:8766/accessibility"
echo "   • Action Executor:     http://localhost:8080"
echo "   • Vision:              http://localhost:8081"
echo "   • RAG Retriever:       http://localhost:8082"
echo "   • Planner:             http://localhost:8083"
echo ""
echo "📊 Process IDs:"
if [ "$PLATFORM" == "macOS" ]; then
    if [ -n "$CAPTURE_PID" ]; then
        echo "   • CaptureService:      $CAPTURE_PID"
    else
        echo "   • CaptureService:      (not available - Xcode required)"
    fi
    if [ -n "$ACCESS_PID" ]; then
        echo "   • AccessibilityBridge: $ACCESS_PID"
    else
        echo "   • AccessibilityBridge: (not available - Xcode required)"
    fi
fi
echo "   • UI Twin:             $UI_TWIN_PID"
echo "   • Action Executor:     $EXECUTOR_PID"
echo "   • Vision:              $VISION_PID"
echo "   • RAG Retriever:       $RAG_PID"
echo "   • Planner:             $PLANNER_PID"
echo ""
echo "📝 Logs:"
echo "   • logs/capture_service.log"
echo "   • logs/accessibility_bridge.log"
echo "   • logs/ui_twin.log"
echo "   • logs/action_executor.log"
echo "   • logs/vision.log"
echo "   • logs/rag_retriever.log"
echo "   • logs/planner.log"
echo ""
echo "🧪 Test the system:"
echo "   curl http://localhost:8080/health"
echo "   curl http://localhost:8083/health"
echo ""
echo "🛑 Stop all services:"
echo "   ./STOP_NATIVE_SERVICES.sh"
echo ""
echo -e "${GREEN}🎉 Shail is ready!${NC}"

