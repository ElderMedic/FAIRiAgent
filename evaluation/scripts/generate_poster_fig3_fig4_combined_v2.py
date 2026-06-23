#!/usr/bin/env python3
"""Compatibility entrypoint for the v2 poster figure.

The canonical implementation lives in evaluate_agent_quality.py so the
reported statistics and poster panels cannot drift apart.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from evaluation.scripts.evaluate_agent_quality import main


if __name__ == "__main__":
    main()
