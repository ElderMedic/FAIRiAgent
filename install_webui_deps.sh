#!/bin/bash
# 安装 WebUI 依赖（Streamlit）

echo "📦 Installing WebUI dependencies..."
echo ""

# 检查是否在虚拟环境中
if [[ -z "$CONDA_DEFAULT_ENV" ]] && [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠️  Warning: Not in a virtual environment!"
    echo "   Recommended: activate your conda/mamba environment first"
    echo "   Example: mamba activate test"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 安装
pip install streamlit>=1.30.0

echo ""
echo "✅ Installation complete!"
echo ""
echo "📋 You can now run:"
echo "   ./start_streamlit.sh  # Start Streamlit UI"

