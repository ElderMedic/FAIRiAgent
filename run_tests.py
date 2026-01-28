#!/usr/bin/env python3
"""
Unified Test Runner for FAIRiAgent (Python version)
Alternative to run_tests.sh for cross-platform compatibility
"""

import sys
import subprocess
import argparse
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    RED = '\033[0;31m'
    NC = '\033[0m'  # No Color


def print_header(text):
    """Print colored header."""
    print(f"{Colors.BLUE}{'=' * 70}{Colors.NC}")
    print(f"{Colors.BLUE}{text}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 70}{Colors.NC}")


def print_success(text):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.NC}")


def print_error(text):
    """Print error message."""
    print(f"{Colors.RED}✗ {text}{Colors.NC}")


def print_warning(text):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.NC}")


def run_command(cmd, description=None):
    """Run a command and return exit code."""
    if description:
        print(f"\n{description}")
    
    try:
        result = subprocess.run(cmd, shell=False, check=False)
        return result.returncode
    except Exception as e:
        print_error(f"Command failed: {e}")
        return 1


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(
        description='Unified Test Runner for FAIRiAgent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py all              # Run all tests
  python run_tests.py fast             # Run fast tests only
  python run_tests.py integration      # Run integration tests only
  python run_tests.py coverage         # Run with coverage report
  python run_tests.py specific test_critic_utils.py  # Run specific test
        """
    )
    
    parser.add_argument(
        'mode',
        nargs='?',
        default='all',
        choices=['all', 'fast', 'integration', 'coverage', 'specific'],
        help='Test mode to run (default: all)'
    )
    
    parser.add_argument(
        'test_file',
        nargs='?',
        help='Specific test file to run (for "specific" mode)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )
    
    args = parser.parse_args()
    
    # Check if pytest is available
    try:
        subprocess.run(['pytest', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("pytest not found. Please install: pip install pytest pytest-asyncio")
        return 1
    
    # Show environment info
    print_header("Test Environment")
    
    try:
        python_version = subprocess.run(
            ['python', '--version'],
            capture_output=True,
            text=True
        ).stdout.strip()
        print(f"Python version: {python_version}")
    except Exception:
        pass
    
    try:
        pytest_version = subprocess.run(
            ['pytest', '--version'],
            capture_output=True,
            text=True
        ).stdout.strip().split('\n')[0]
        print(f"Pytest version: {pytest_version}")
    except Exception:
        pass
    
    print(f"Working directory: {Path.cwd()}")
    print()
    
    # Build pytest command
    pytest_cmd = ['pytest', 'tests/']
    pytest_opts = ['-v', '--tb=short']
    
    if args.verbose:
        pytest_opts.append('-vv')
    
    # Run tests based on mode
    if args.mode == 'all':
        print_header("Running All Tests (67 tests)")
        exit_code = run_command(pytest_cmd + pytest_opts)
    
    elif args.mode == 'fast':
        print_header("Running Fast Tests (Unit Tests Only)")
        print_warning("Excluding: integration and slow tests")
        exit_code = run_command(
            pytest_cmd + pytest_opts + ['-m', 'not integration and not slow']
        )
    
    elif args.mode == 'integration':
        print_header("Running Integration Tests")
        print_warning("Requires: FAIR-DS API and MinerU server running")
        exit_code = run_command(
            pytest_cmd + pytest_opts + ['-m', 'integration']
        )
    
    elif args.mode == 'coverage':
        print_header("Running All Tests with Coverage")
        
        # Check if pytest-cov is available
        try:
            import pytest_cov  # noqa: F401
        except ImportError:
            print_warning("pytest-cov not installed. Installing...")
            subprocess.run(['pip', 'install', 'pytest-cov'], check=False)
        
        exit_code = run_command(
            pytest_cmd + pytest_opts + [
                '--cov=fairifier',
                '--cov-report=html',
                '--cov-report=term-missing',
                '--cov-report=term:skip-covered'
            ]
        )
        
        if exit_code == 0:
            print_success("Coverage report generated at: htmlcov/index.html")
            
            # Save summary to .memory
            from datetime import datetime
            memory_dir = Path('.memory/test-reports')
            memory_dir.mkdir(parents=True, exist_ok=True)
            summary_file = memory_dir / 'last-coverage-run.txt'
            summary_file.write_text(f"Coverage report generated at {datetime.now()}\n")
            print_success("Test summary saved to: .memory/test-reports/")
    
    elif args.mode == 'specific':
        if not args.test_file:
            print_error("Please specify a test file")
            print("Usage: python run_tests.py specific <test_file>")
            return 1
        
        test_path = Path('tests') / args.test_file
        if not test_path.exists():
            print_error(f"Test file not found: {test_path}")
            return 1
        
        print_header(f"Running Specific Test: {args.test_file}")
        exit_code = run_command(['pytest', str(test_path)] + pytest_opts)
    
    else:
        print_error(f"Unknown test mode: {args.mode}")
        return 1
    
    # Report results
    print()
    if exit_code == 0:
        print_success("All tests passed!")
        return 0
    else:
        print_error("Some tests failed")
        return exit_code


if __name__ == '__main__':
    sys.exit(main())
