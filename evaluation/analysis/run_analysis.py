#!/usr/bin/env python3
"""
Main script to run comprehensive evaluation analysis.

Usage:
    python evaluation/analysis/run_analysis.py [--runs-dir PATH] [--output-dir PATH] [--pattern PATTERN]
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from evaluation.analysis.reports import ReportGenerator


def main():
    parser = argparse.ArgumentParser(
        description='Generate comprehensive evaluation analysis report'
    )
    parser.add_argument(
        '--runs-dir',
        type=Path,
        default=Path('evaluation/runs'),
        help='Path to evaluation/runs directory (default: evaluation/runs)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('evaluation/analysis/output'),
        help='Output directory for reports and figures (default: evaluation/analysis/output)'
    )
    parser.add_argument(
        '--pattern',
        type=str,
        default=None,
        help='Optional pattern to filter runs (e.g., "qwen_*", "openai_*")'
    )
    
    args = parser.parse_args()
    
    # Generate report
    generator = ReportGenerator(
        runs_dir=args.runs_dir,
        output_dir=args.output_dir,
        pattern=args.pattern
    )
    
    generator.generate_all()


if __name__ == '__main__':
    main()








