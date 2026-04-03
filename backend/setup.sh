#!/bin/bash
# Setup virtual environment for Mail Merge Backend

set -e

echo "🔧 Setting up virtual environment..."

cd "$(dirname "$0")"

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment with Python 3.9..."
    python3 -m venv venv
fi

# Activate venv
echo "✅ Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Check .env
if [ ! -f .env ]; then
    echo "⚠️  .env not found. Creating from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env and add your GEMINI_API_KEY"
    echo "   Get API key from: https://aistudio.google.com/app/apikey"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To activate venv in future:"
echo "  source venv/bin/activate"
echo ""
echo "To start backend:"
echo "  ./start.sh"
echo "  hoặc: source venv/bin/activate && uvicorn main:app --reload --port 8000"
