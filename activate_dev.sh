#!/bin/bash
# Development environment activation script for ha-saxo-portfolio
# Usage: source ./activate_dev.sh

if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Development environment activated!"
    echo "Python: $(python --version)"
    echo "pip: $(pip --version)"
    echo ""
    echo "Available commands:"
    echo "  ruff check .           # Check code style"
    echo "  ruff format .          # Format code"
    echo "  python -m pytest tests/  # Run tests"
    echo "  mypy custom_components/  # Type checking"
    echo ""
    echo "To deactivate: deactivate"
else
    echo "❌ Virtual environment not found. Please run: python3 -m venv venv"
fi