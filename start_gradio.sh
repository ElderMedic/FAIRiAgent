#!/bin/bash
# 启动 Gradio WebUI

echo "🚀 Starting Gradio WebUI for FAIRifier..."
echo ""
echo "📋 Interface will be available at: http://localhost:7860"
echo "📚 API Documentation: http://localhost:7860/docs"
echo "⏹️  Press Ctrl+C to stop"
echo ""

# 激活 FAIRiAgent mamba 环境并启动
cd "$(dirname "$0")"
mamba run -n FAIRiAgent python fairifier/apps/ui/gradio_app.py

