#!/bin/bash
# Setup script for LangGraph integration

set -e

echo "🔧 Setting up LangGraph integration for Shail..."

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: Must run from shail_master root directory"
    exit 1
fi

# Install LangGraph via pip (recommended for production)
echo "📦 Installing LangGraph via pip..."
python3 -m pip install --upgrade pip
python3 -m pip install langgraph>=0.2.0 langgraph-checkpoint>=0.2.0

# Alternative: Install from local source (for development)
# Uncomment if you want to use the cloned source:
# echo "📦 Installing LangGraph from local source..."
# cd langgraph/libs/langgraph
# python3 -m pip install -e .
# cd ../../..

# Install other dependencies
echo "📦 Installing other dependencies..."
python3 -m pip install -r requirements.txt

# Verify installation
echo "✅ Verifying installation..."
python3 -c "
from shail.orchestration.langgraph_integration import get_state_graph
StateGraph = get_state_graph()
print('✅ LangGraph integration working!')
print(f'   StateGraph class: {StateGraph}')
"

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Next steps:"
echo "1. Create .env file with API keys (see docs/LANGGRAPH_SETUP_COMPLETE.md)"
echo "2. Run tests: python3 -m pytest tests/test_langgraph_integration.py -v"
echo "3. Start Shail and test LangGraph integration"
