#!/bin/bash
# 启动 Streamlit WebUI

echo "🚀 Starting Streamlit WebUI for FAIRifier..."
echo ""
echo "📋 Interface will be available at: http://localhost:8501"
echo "⏹️  Press Ctrl+C to stop"
echo ""

# 激活 conda 环境（如果需要）
# conda activate test

# 启动 Streamlit
cd "$(dirname "$0")"
streamlit run fairifier/apps/ui/streamlit_app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false


