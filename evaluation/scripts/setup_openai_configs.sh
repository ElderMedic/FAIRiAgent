#!/bin/bash
# Setup OpenAI API keys in model configs
# Usage: ./setup_openai_configs.sh [your_openai_api_key]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/../config/model_configs"

# Get API key from argument or environment variable
if [ -n "$1" ]; then
    API_KEY="$1"
elif [ -n "$OPENAI_API_KEY" ]; then
    API_KEY="$OPENAI_API_KEY"
else
    echo "❌ Error: OpenAI API key not provided"
    echo "Usage: $0 <your_openai_api_key>"
    echo "   OR: export OPENAI_API_KEY=your_key_here"
    exit 1
fi

echo "🔑 Setting up OpenAI API keys in model configs..."

# List of OpenAI config files
CONFIGS=(
    "openai_gpt5.env"
    "openai_gpt4.1.env"
    "openai_gpt4o.env"
    "openai_o3.env"
)

for config_file in "${CONFIGS[@]}"; do
    config_path="$CONFIG_DIR/$config_file"
    if [ -f "$config_path" ]; then
        # Use sed to replace the API key (works on both macOS and Linux)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s|LLM_API_KEY=.*|LLM_API_KEY=$API_KEY|" "$config_path"
        else
            # Linux
            sed -i "s|LLM_API_KEY=.*|LLM_API_KEY=$API_KEY|" "$config_path"
        fi
        echo "  ✅ Updated $config_file"
    else
        echo "  ⚠️  Config file not found: $config_file"
    fi
done

echo ""
echo "✅ All OpenAI configs updated!"
echo ""
echo "📝 Note: If any models don't exist (e.g., gpt-5, o3), you may need to:"
echo "   1. Check OpenAI's available models: https://platform.openai.com/docs/models"
echo "   2. Update the FAIRIFIER_LLM_MODEL in the config files"
echo "   3. Common alternatives:"
echo "      - o3 -> o1 or o3-mini"
echo "      - gpt-4.1 -> gpt-4-turbo or gpt-4"
echo "      - gpt-5 -> gpt-4o (if gpt-5 doesn't exist yet)"

