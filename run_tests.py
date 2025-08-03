#!/usr/bin/env python3
"""
Test runner script for Meta MCP integration system.

This script provides an easy way to run different sets of tests with
appropriate configuration and reporting.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle output."""
    print(f"\n🧪 {description}")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 50)

    try:
        subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"❌ Command not found: {cmd[0]}")
        print(
            "Make sure pytest is installed: pip install pytest pytest-asyncio pytest-cov"
        )
        return False


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(
        description="Run Meta MCP integration system tests"
    )
    parser.add_argument(
        "--type",
        choices=["all", "unit", "integration", "fast"],
        default="fast",
        help="Type of tests to run",
    )
    parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage reports"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Run tests in verbose mode"
    )
    parser.add_argument("--file", "-f", help="Run tests from specific file")

    args = parser.parse_args()

    # Ensure we're in the right directory
    project_root = Path(__file__).parent
    if not (project_root / "src" / "meta_mcp").exists():
        print("❌ Error: Must be run from the project root directory")
        sys.exit(1)

    # Base pytest command
    cmd = ["python", "-m", "pytest"]

    # Add verbosity
    if args.verbose:
        cmd.append("-v")

    # Add coverage if requested
    if args.coverage:
        cmd.extend(
            [
                "--cov=src/meta_mcp",
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov",
            ]
        )

    # Select test type
    if args.file:
        cmd.append(f"tests/{args.file}")
        description = f"Running tests from {args.file}"
    elif args.type == "all":
        cmd.append("tests/")
        description = "Running all tests"
    elif args.type == "unit":
        cmd.extend(["-m", "not integration", "tests/"])
        description = "Running unit tests only"
    elif args.type == "integration":
        cmd.extend(["-m", "integration", "tests/"])
        description = "Running integration tests only"
    elif args.type == "fast":
        cmd.extend(["-m", "not slow", "tests/"])
        description = "Running fast tests only"

    print("🚀 Meta MCP Integration System Test Runner")
    print("=" * 50)

    success = run_command(cmd, description)

    if success:
        print("\n🎉 All tests completed successfully!")

        if args.coverage:
            print("\n📊 Coverage report generated:")
            print("  - Terminal: shown above")
            print("  - HTML: htmlcov/index.html")

        print("\n💡 Test Tips:")
        print("  - Run specific file: --file test_integration_manager.py")
        print("  - Run with coverage: --coverage")
        print("  - Run only fast tests: --type fast")
        print("  - Run integration tests: --type integration")

    else:
        print("\n❌ Some tests failed. Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
