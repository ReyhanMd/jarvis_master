#!/bin/bash

# 🚀 Shail Unified Startup Script
# Starts ALL services: Native, Python, Redis, Worker, API, and UI
# Usage: ./start_shail_all.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Starting Shail - Complete System"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check for required environment variables
if [ -z "$GEMINI_API_KEY" ]; then
    if [ -f ".env" ]; then
        echo "📋 Loading .env file..."
        export $(grep -v '^#' .env | xargs)
    else
        echo -e "${YELLOW}⚠️  GEMINI_API_KEY not set and no .env file found${NC}"
        echo "   Create .env file or export GEMINI_API_KEY"
        echo "   Continuing anyway (some features may not work)..."
    fi
fi

# Create logs directory
mkdir -p logs

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
# 1. Native Services (macOS)
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Native Services (macOS)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "📱 macOS detected - Starting native services..."
    
    # Check if native services are already running
    if pgrep -f "CaptureService" > /dev/null; then
        echo -e "${GREEN}✅ CaptureService is already running${NC}"
    else
        echo "🎥 Starting CaptureService..."
        echo -e "${YELLOW}   Note: If not running from Xcode, opening Xcode project...${NC}"
        
        # Try to use run_native_services.sh first
        if [ -f "./run_native_services.sh" ]; then
            echo "   Using run_native_services.sh..."
            ./run_native_services.sh &
            sleep 3
        else
            # Fallback: Open Xcode project
            echo "   Opening CaptureService.xcodeproj in Xcode..."
            open -a Xcode native/mac/CaptureService/CaptureService.xcodeproj 2>/dev/null || true
            echo -e "${YELLOW}   Please build and run CaptureService in Xcode (⌘+R)${NC}"
        fi
    fi
    
    if pgrep -f "AccessibilityBridge" > /dev/null; then
        echo -e "${GREEN}✅ AccessibilityBridge is already running${NC}"
    else
        echo "♿ Starting AccessibilityBridge..."
        echo -e "${YELLOW}   Note: If not running from Xcode, opening Xcode project...${NC}"
        
        # Try to use run_native_services.sh first
        if [ -f "./run_native_services.sh" ]; then
            # Already handled above
            sleep 2
        else
            # Fallback: Open Xcode project
            echo "   Opening AccessibilityBridge.xcodeproj in Xcode..."
            open -a Xcode native/mac/AccessibilityBridge/AccessibilityBridge.xcodeproj 2>/dev/null || true
            echo -e "${YELLOW}   Please build and run AccessibilityBridge in Xcode (⌘+R)${NC}"
        fi
    fi
    
    echo ""
    echo -e "${BLUE}💡 Tip: Native services need permissions.${NC}"
    echo "   If permission dialogs appear, grant them in System Settings."
    echo ""
else
    echo -e "${YELLOW}⚠️  Non-macOS platform - Skipping native services${NC}"
    echo ""
fi

# ===============================
# 2. Redis
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Redis (Task Queue)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if check_port 6379; then
    echo -e "${GREEN}✅ Redis is already running on port 6379${NC}"
else
    if command -v redis-server >/dev/null 2>&1; then
        echo "🔄 Starting Redis..."
        redis-server > logs/redis.log 2>&1 &
        REDIS_PID=$!
        echo "   PID: $REDIS_PID"
        sleep 2
        if check_port 6379; then
            echo -e "${GREEN}✅ Redis started successfully${NC}"
        else
            echo -e "${RED}❌ Redis failed to start${NC}"
        fi
    else
        echo -e "${RED}❌ redis-server not found${NC}"
        echo "   Install Redis: brew install redis"
        echo "   Or start Redis manually in another terminal"
    fi
fi
echo ""

# ===============================
# 3. Python Services
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Python Services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check for virtual environment
if [ ! -d "services_env" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating...${NC}"
    python3 -m venv services_env
fi

# Activate virtual environment
source services_env/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install -q --upgrade pip > /dev/null 2>&1

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
if check_port 8080; then
    echo -e "${GREEN}✅ UI Twin is already running${NC}"
else
    echo "🎭 Starting UI Twin Service..."
    cd services/ui_twin
    python service.py > ../../logs/ui_twin.log 2>&1 &
    UI_TWIN_PID=$!
    cd ../..
    echo "   PID: $UI_TWIN_PID"
    sleep 2
fi

# Start Action Executor
if check_port 8080; then
    echo -e "${GREEN}✅ Action Executor is already running${NC}"
else
    echo "🎮 Starting Action Executor Service..."
    cd services/action_executor
    python service.py > ../../logs/action_executor.log 2>&1 &
    EXECUTOR_PID=$!
    cd ../..
    echo "   PID: $EXECUTOR_PID"
    wait_for_service "Action Executor" 8080
fi

# Start Vision
if check_port 8081; then
    echo -e "${GREEN}✅ Vision is already running${NC}"
else
    echo "👁️  Starting Vision Service..."
    cd services/vision
    python service.py > ../../logs/vision.log 2>&1 &
    VISION_PID=$!
    cd ../..
    echo "   PID: $VISION_PID"
    wait_for_service "Vision" 8081
fi

# Start RAG Retriever
if check_port 8082; then
    echo -e "${GREEN}✅ RAG Retriever is already running${NC}"
else
    echo "🗄️  Starting RAG Retriever Service..."
    cd services/rag_retriever
    python service.py > ../../logs/rag_retriever.log 2>&1 &
    RAG_PID=$!
    cd ../..
    echo "   PID: $RAG_PID"
    wait_for_service "RAG Retriever" 8082
fi

# Start Planner
if check_port 8083; then
    echo -e "${GREEN}✅ Planner is already running${NC}"
else
    echo "📋 Starting Planner Service..."
    if [ -z "$GEMINI_API_KEY" ]; then
        echo -e "${YELLOW}⚠️  GEMINI_API_KEY not set. LLM features will be limited.${NC}"
    fi
    cd services/planner
    python service.py > ../../logs/planner.log 2>&1 &
    PLANNER_PID=$!
    cd ../..
    echo "   PID: $PLANNER_PID"
    wait_for_service "Planner" 8083
fi

echo ""

# ===============================
# 4. Shail Core Services
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Shail Core Services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start Task Worker
if pgrep -f "task_worker" > /dev/null; then
    echo -e "${GREEN}✅ Task Worker is already running${NC}"
else
    echo "👷 Starting Task Worker..."
    if [ -z "$GEMINI_API_KEY" ]; then
        echo -e "${RED}❌ GEMINI_API_KEY not set. Worker cannot start.${NC}"
        echo "   Set it: export GEMINI_API_KEY=\"your-key\""
    else
        python -m shail.workers.task_worker > logs/task_worker.log 2>&1 &
        WORKER_PID=$!
        echo "   PID: $WORKER_PID"
        sleep 2
        echo -e "${GREEN}✅ Task Worker started${NC}"
    fi
fi

# Start Shail API
if check_port 8000; then
    echo -e "${GREEN}✅ Shail API is already running${NC}"
else
    echo "🌐 Starting Shail API..."
    uvicorn apps.shail.main:app --reload --host 0.0.0.0 --port 8000 > logs/shail_api.log 2>&1 &
    API_PID=$!
    echo "   PID: $API_PID"
    wait_for_service "Shail API" 8000
fi

echo ""

# ===============================
# 5. Shail UI (Optional)
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  Shail UI (Optional)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -d "apps/shail-ui" ]; then
    if check_port 5173; then
        echo -e "${GREEN}✅ Shail UI is already running${NC}"
    else
        echo "🎨 Starting Shail UI..."
        echo -e "${YELLOW}   Starting in background...${NC}"
        cd apps/shail-ui
        
        # Check if node_modules exists
        if [ ! -d "node_modules" ]; then
            echo "   Installing dependencies (first time only)..."
            npm install > ../../logs/shail_ui_install.log 2>&1
        fi
        
        npm run dev > ../../logs/shail_ui.log 2>&1 &
        UI_PID=$!
        cd ../..
        echo "   PID: $UI_PID"
        echo "   UI will be available at http://localhost:5173"
        sleep 3
    fi
else
    echo -e "${YELLOW}⚠️  Shail UI directory not found - Skipping${NC}"
fi

echo ""

# ===============================
# Summary
# ===============================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Shail System Started"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Service Endpoints:"
echo "   • CaptureService:      ws://localhost:8765/capture"
echo "   • AccessibilityBridge: ws://localhost:8766/accessibility"
echo "   • Action Executor:     http://localhost:8080"
echo "   • Vision:              http://localhost:8081"
echo "   • RAG Retriever:       http://localhost:8082"
echo "   • Planner:             http://localhost:8083"
echo "   • Shail API:           http://localhost:8000"
echo "   • Shail UI:            http://localhost:5173"
echo "   • API Docs:            http://localhost:8000/docs"
echo ""
echo "📊 Check Status:"
echo "   ./check_native_health.sh  # Native services"
echo "   curl http://localhost:8080/health  # Python services"
echo "   redis-cli ping  # Redis"
echo ""
echo "📝 Logs:"
echo "   tail -f logs/*.log  # Watch all logs"
echo ""
echo "🛑 Stop All Services:"
echo "   ./stop_shail_all.sh  # (or Ctrl+C in each terminal)"
echo ""
echo -e "${GREEN}🎉 Shail is ready!${NC}"
echo ""
echo "💡 Next Steps:"
echo "   1. Open http://localhost:5173 in your browser"
echo "   2. Or use the API: curl http://localhost:8000/docs"
echo "   3. Send a task: curl -X POST http://localhost:8000/tasks -H 'Content-Type: application/json' -d '{\"description\": \"test\"}'"
echo ""

