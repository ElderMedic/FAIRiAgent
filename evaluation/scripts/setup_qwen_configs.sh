#!/bin/bash
# Extract Dashscope API key from root .env and populate Qwen configs

BASE_DIR="/Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent"
cd "$BASE_DIR"

# Try to extract API key from root .env
if [ -f ".env" ]; then
    # Try to get Qwen/Dashscope API key
    DASHSCOPE_KEY=$(grep -E "^(LLM_API_KEY|QWEN.*KEY|DASHSCOPE.*KEY)=" .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    
    if [ -n "$DASHSCOPE_KEY" ] && [ "$DASHSCOPE_KEY" != "your_api_key_here" ]; then
        echo "✅ Found API key in .env"
        
        # Update all Qwen configs
        for config in evaluation/config/model_configs/qwen_*.env; do
            if [ -f "$config" ]; then
                # Use sed to replace the placeholder
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    # macOS sed
                    sed -i '' "s|LLM_API_KEY=your_dashscope_api_key_here|LLM_API_KEY=$DASHSCOPE_KEY|g" "$config"
                else
                    # Linux sed
                    sed -i "s|LLM_API_KEY=your_dashscope_api_key_here|LLM_API_KEY=$DASHSCOPE_KEY|g" "$config"
                fi
                echo "  Updated: $(basename $config)"
            fi
        done
        echo "✅ All Qwen configs updated with API key"
    else
        echo "⚠️  Could not find valid API key in .env"
        echo "   Please manually update evaluation/config/model_configs/qwen_*.env files"
    fi
else
    echo "⚠️  .env file not found in root directory"
    echo "   Please manually update evaluation/config/model_configs/qwen_*.env files"
fi

