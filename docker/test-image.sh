#!/bin/bash
# Quick test script for fairiagent Docker image

set -e

IMAGE_TAG="${1:-fairiagent:1.1.0-mem0}"

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║              🐳 Testing FAIRiAgent Docker Image                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Image: $IMAGE_TAG"
echo ""

# Test 1: Image exists
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 1: Image exists"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker image inspect "$IMAGE_TAG" > /dev/null 2>&1; then
    echo "✅ Image found"
    docker images "$IMAGE_TAG" --format "   ID: {{.ID}}, Size: {{.Size}}, Created: {{.CreatedAt}}"
else
    echo "❌ Image not found: $IMAGE_TAG"
    exit 1
fi

# Test 2: CLI help
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2: CLI Help"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker run --rm "$IMAGE_TAG" python run_fairifier.py --help > /dev/null 2>&1; then
    echo "✅ CLI help works"
else
    echo "❌ CLI help failed"
    exit 1
fi

# Test 3: Config info
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3: Config Info"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if docker run --rm "$IMAGE_TAG" python run_fairifier.py config-info > /dev/null 2>&1; then
    echo "✅ Config info works"
    docker run --rm "$IMAGE_TAG" python run_fairifier.py config-info 2>&1 | grep -E "LLM Provider|mem0|Version" | head -5 || echo "   (Config output available)"
else
    echo "❌ Config info failed"
    exit 1
fi

# Test 4: Python packages
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4: Key Dependencies"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DEPS_CHECK=$(docker run --rm "$IMAGE_TAG" python -c "
try:
    import langgraph
    import langchain
    import fastapi
    import mem0
    print('✅ All key dependencies installed')
    print('   • langgraph:', langgraph.__version__)
    print('   • langchain:', langchain.__version__)
    print('   • mem0: installed')
except ImportError as e:
    print('❌ Missing dependency:', e)
    exit(1)
" 2>&1)
echo "$DEPS_CHECK"

# Test 5: File structure
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 5: Application Structure"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
FILE_CHECK=$(docker run --rm "$IMAGE_TAG" sh -c "
if [ -f run_fairifier.py ] && [ -d fairifier ] && [ -d kb ]; then
    echo '✅ Application files present'
    echo '   • run_fairifier.py: exists'
    echo '   • fairifier/: exists'
    echo '   • kb/: exists'
    ls fairifier/services/*.py 2>/dev/null | grep mem0 > /dev/null && echo '   • mem0_service.py: found' || echo '   ⚠️  mem0_service.py: not found'
else
    echo '❌ Missing application files'
    exit 1
fi
" 2>&1)
echo "$FILE_CHECK"

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                        ✅ ALL TESTS PASSED                             ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Image is ready for deployment!"
echo ""
echo "Next steps:"
echo "  • Run API: docker run -p 8000:8000 $IMAGE_TAG"
echo "  • Use CLI: docker run --rm $IMAGE_TAG python run_fairifier.py --help"
echo "  • Deploy: cd docker && docker-compose up -d"
echo ""
