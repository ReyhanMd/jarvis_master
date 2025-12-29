#!/bin/bash

# Start only Python services (skip native services)
# Use this if you don't have Xcode installed yet

set -e

echo "🚀 Starting Shail Python Services Only"
echo "========================================"
echo "⚠️  Note: Native services (capture/accessibility) are skipped"
echo "   Python services will work, but won't receive real-time UI data"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

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

# Start UI Twin (will fail to connect to native services, but that's OK)
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
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Python Services Started"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Service Endpoints:"
echo "   • Action Executor:     http://localhost:8080"
echo "   • Vision:              http://localhost:8081"
echo "   • RAG Retriever:       http://localhost:8082"
echo "   • Planner:             http://localhost:8083"
echo ""
echo "📊 Process IDs:"
echo "   • UI Twin:             $UI_TWIN_PID"
echo "   • Action Executor:     $EXECUTOR_PID"
echo "   • Vision:              $VISION_PID"
echo "   • RAG Retriever:       $RAG_PID"
echo "   • Planner:             $PLANNER_PID"
echo ""
echo "📝 Logs:"
echo "   • logs/ui_twin.log"
echo "   • logs/action_executor.log"
echo "   • logs/vision.log"
echo "   • logs/rag_retriever.log"
echo "   • logs/planner.log"
echo ""
echo "🧪 Test the services:"
echo "   curl http://localhost:8080/health"
echo "   curl http://localhost:8081/health"
echo "   curl http://localhost:8082/health"
echo "   curl http://localhost:8083/health"
echo ""
echo -e "${GREEN}🎉 Python services are ready!${NC}"
echo ""
echo "⚠️  Note: Without native services, you can still:"
echo "   • Execute actions (click, type) via Action Executor"
echo "   • Use Vision for OCR on screenshots"
echo "   • Use RAG for context retrieval"
echo "   • Use Planner for task orchestration"
echo ""
echo "   But you won't have:"
echo "   • Real-time screen capture"
echo "   • Real-time accessibility events"
echo "   • UI Twin element tracking"
echo ""
echo "🛑 Stop all services:"
echo "   ./STOP_NATIVE_SERVICES.sh"

