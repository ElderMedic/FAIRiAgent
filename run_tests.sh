#!/bin/bash
# Unified Test Runner for FAIRiAgent
# This script runs all tests with various configurations

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Parse command line arguments
TEST_MODE="${1:-all}"  # all, fast, integration, coverage
VERBOSE="${2:-}"

# Show usage if help requested
if [[ "$TEST_MODE" == "-h" ]] || [[ "$TEST_MODE" == "--help" ]]; then
    echo "Usage: $0 [MODE] [OPTIONS]"
    echo ""
    echo "Modes:"
    echo "  all          - Run all tests (default)"
    echo "  fast         - Run only fast unit tests (exclude integration/slow)"
    echo "  integration  - Run only integration tests (requires services)"
    echo "  coverage     - Run all tests with coverage report"
    echo "  specific     - Run specific test file (pass filename as 2nd arg)"
    echo ""
    echo "Options:"
    echo "  -v, --verbose  - Verbose output"
    echo ""
    echo "Examples:"
    echo "  $0 all              # Run all tests"
    echo "  $0 fast             # Run fast tests only"
    echo "  $0 integration      # Run integration tests only"
    echo "  $0 coverage         # Run with coverage report"
    echo "  $0 specific test_critic_utils.py  # Run specific test file"
    exit 0
fi

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    print_error "pytest not found. Please install: pip install pytest pytest-asyncio"
    exit 1
fi

# Show test environment info
print_header "Test Environment"
echo "Python version: $(python --version 2>&1)"
echo "Pytest version: $(pytest --version 2>&1 | head -1)"
echo "Working directory: $(pwd)"
echo ""

# Build pytest command
PYTEST_CMD="pytest tests/"
PYTEST_OPTS="-v --tb=short"

if [[ "$VERBOSE" == "-v" ]] || [[ "$VERBOSE" == "--verbose" ]]; then
    PYTEST_OPTS="$PYTEST_OPTS -vv"
fi

# Run tests based on mode
case "$TEST_MODE" in
    "all")
        print_header "Running All Tests (67 tests)"
        $PYTEST_CMD $PYTEST_OPTS
        ;;
    
    "fast")
        print_header "Running Fast Tests (Unit Tests Only)"
        print_warning "Excluding: integration and slow tests"
        $PYTEST_CMD $PYTEST_OPTS -m "not integration and not slow"
        ;;
    
    "integration")
        print_header "Running Integration Tests"
        print_warning "Requires: FAIR-DS API and MinerU server running"
        $PYTEST_CMD $PYTEST_OPTS -m "integration"
        ;;
    
    "coverage")
        print_header "Running All Tests with Coverage"
        
        # Check if pytest-cov is available
        if ! python -c "import pytest_cov" 2>/dev/null; then
            print_error "pytest-cov not installed. Installing..."
            pip install pytest-cov
        fi
        
        $PYTEST_CMD $PYTEST_OPTS \
            --cov=fairifier \
            --cov-report=html \
            --cov-report=term-missing \
            --cov-report=term:skip-covered
        
        print_success "Coverage report generated at: htmlcov/index.html"
        
        # Save summary to .memory
        mkdir -p .memory/test-reports
        echo "Coverage report generated at $(date)" > .memory/test-reports/last-coverage-run.txt
        print_success "Test summary saved to: .memory/test-reports/"
        ;;
    
    "specific")
        if [[ -z "$2" ]]; then
            print_error "Please specify a test file"
            echo "Usage: $0 specific <test_file>"
            exit 1
        fi
        
        TEST_FILE="$2"
        if [[ ! -f "tests/$TEST_FILE" ]]; then
            print_error "Test file not found: tests/$TEST_FILE"
            exit 1
        fi
        
        print_header "Running Specific Test: $TEST_FILE"
        pytest "tests/$TEST_FILE" $PYTEST_OPTS
        ;;
    
    *)
        print_error "Unknown test mode: $TEST_MODE"
        echo "Run '$0 --help' for usage information"
        exit 1
        ;;
esac

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    print_success "All tests passed!"
    exit 0
else
    echo ""
    print_error "Some tests failed"
    exit 1
fi
