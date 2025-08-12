#!/bin/bash

# GHL Customer Qualification Webhook - Development Setup Script
# This script automates the installation of development dependencies and environment setup

set -e  # Exit on any error

echo "🚀 Setting up GHL Customer Qualification Webhook development environment..."
echo

# Check Python version
echo "📋 Checking Python version..."
python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
required_version="3.9"

if python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
    echo "✅ Python $python_version is compatible (>= $required_version)"
else
    echo "❌ Python $python_version is not compatible. Please install Python >= $required_version"
    exit 1
fi
echo

# Install development dependencies
echo "📦 Installing development dependencies..."
if pip install -e .[dev]; then
    echo "✅ Development dependencies installed successfully"
else
    echo "❌ Failed to install development dependencies"
    echo "   Trying fallback installation method..."
    if pip install -r requirements.txt && pip install pytest pytest-asyncio black isort; then
        echo "✅ Dependencies installed via fallback method"
    else
        echo "❌ Failed to install dependencies. Please check your Python environment."
        exit 1
    fi
fi
echo

# Set up environment file
echo "🔧 Setting up environment configuration..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env file from .env.example template"
        echo "⚠️  Please edit .env file with your actual API keys before running the application"
    else
        echo "❌ .env.example file not found"
        exit 1
    fi
else
    echo "✅ .env file already exists"
fi
echo

# Validate development tools installation
echo "🔍 Validating development tools installation..."

# Check pytest
if python3 -c "import pytest" 2>/dev/null; then
    pytest_version=$(python3 -c "import pytest; print(pytest.__version__)")
    echo "✅ pytest $pytest_version is installed"
else
    echo "❌ pytest is not properly installed"
    exit 1
fi

# Check black
if python3 -c "import black" 2>/dev/null; then
    black_version=$(python3 -c "import black; print(black.__version__)")
    echo "✅ black $black_version is installed"
else
    echo "❌ black is not properly installed"
    exit 1
fi

# Check isort
if python3 -c "import isort" 2>/dev/null; then
    isort_version=$(python3 -c "import isort; print(isort.__version__)")
    echo "✅ isort $isort_version is installed"
else
    echo "❌ isort is not properly installed"
    exit 1
fi

# Check pytest-asyncio
if python3 -c "import pytest_asyncio" 2>/dev/null; then
    echo "✅ pytest-asyncio is installed"
else
    echo "❌ pytest-asyncio is not properly installed"
    exit 1
fi
echo

# Install pre-commit hooks if pre-commit is available
echo "🪝 Setting up pre-commit hooks..."
if command -v pre-commit >/dev/null 2>&1; then
    if [ -f .pre-commit-config.yaml ]; then
        pre-commit install
        echo "✅ Pre-commit hooks installed"
    else
        echo "⚠️  .pre-commit-config.yaml not found, skipping pre-commit setup"
    fi
else
    echo "⚠️  pre-commit not installed. Install with: pip install pre-commit"
    echo "   Then run: pre-commit install"
fi
echo

# Test basic functionality
echo "🧪 Running basic validation tests..."

# Test code formatting tools
echo "   Testing Black formatter..."
if black --check --diff src/ >/dev/null 2>&1; then
    echo "   ✅ Code is properly formatted with Black"
else
    echo "   ⚠️  Code formatting issues detected. Run: black src/"
fi

echo "   Testing isort import sorting..."
if isort --check-only src/ >/dev/null 2>&1; then
    echo "   ✅ Imports are properly sorted with isort"
else
    echo "   ⚠️  Import sorting issues detected. Run: isort src/"
fi

# Test if tests can run
echo "   Testing pytest execution..."
if python -m pytest --version >/dev/null 2>&1; then
    echo "   ✅ pytest is ready to run tests"
else
    echo "   ❌ pytest execution test failed"
fi
echo

# Summary
echo "🎉 Development environment setup complete!"
echo
echo "📝 Next steps:"
echo "   1. Edit .env file with your actual API keys"
echo "   2. Run tests: python -m pytest"
echo "   3. Format code: black src/"
echo "   4. Sort imports: isort src/"
echo "   5. Start development server: python -m src.main"
echo
echo "📚 Useful commands:"
echo "   • Run all tests: python -m pytest"
echo "   • Run specific test: python test_qualification_agent.py"
echo "   • Format code: black src/"
echo "   • Sort imports: isort src/"
echo "   • Check health: curl http://localhost:8000/health"
echo
