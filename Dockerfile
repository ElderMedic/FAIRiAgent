# FAIRiAgent Dockerfile
# Multi-purpose Dockerfile supporting CLI and API modes

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# - gcc, g++: Required for building some Python packages
# - curl: For health checks and debugging
# - git: For potential git-based dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright browsers if playwright is installed
# Playwright requires additional system dependencies for browsers
# Note: This step is optional - if playwright isn't used, it will be skipped
RUN if python -c "import playwright" 2>/dev/null; then \
        apt-get update && \
        apt-get install -y \
            libnss3 \
            libnspr4 \
            libatk1.0-0 \
            libatk-bridge2.0-0 \
            libcups2 \
            libdrm2 \
            libdbus-1-3 \
            libxkbcommon0 \
            libxcomposite1 \
            libxdamage1 \
            libxfixes3 \
            libxrandr2 \
            libgbm1 \
            libasound2 \
            libpango-1.0-0 \
            libcairo2 \
        && rm -rf /var/lib/apt/lists/* && \
        (playwright install chromium || echo "Warning: Playwright browser installation failed") && \
        (playwright install-deps chromium || echo "Warning: Playwright deps installation failed"); \
    else \
        echo "Playwright not installed, skipping browser installation"; \
    fi

# Copy application code
COPY fairifier/ ./fairifier/
COPY kb/ ./kb/
COPY run_fairifier.py .
COPY langgraph.json .
COPY pyproject.toml .

# Create necessary directories
RUN mkdir -p output logs

# Expose ports
EXPOSE 8000

# Add healthcheck (for API mode)
# For CLI mode, run with: docker run --no-healthcheck ...
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/docs 2>/dev/null || exit 1

# Set default command (can be overridden)
# Examples:
#   docker run fairiagent                                    # Run API (default)
#   docker run fairiagent python run_fairifier.py --help    # Show help
#   docker run fairiagent python run_fairifier.py process document.pdf  # CLI
CMD ["python", "run_fairifier.py", "api"]
