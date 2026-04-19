#!/bin/bash
# Mail Merge Placeholder System - Backend Startup Script

set -e

cd "$(dirname "$0")"

echo "🚀 Starting Mail Merge Placeholder System Backend..."

# Activate venv
if [ -d "venv" ]; then
    echo "✅ Activating virtual environment..."
    source venv/bin/activate
else
    echo "❌ Virtual environment not found!"
    echo "Run ./setup.sh first"
    exit 1
fi

# Check .env file
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env file and add your GEMINI_API_KEY"
    echo "   Get API key from: https://aistudio.google.com/app/apikey"
    exit 1
fi

# Start server
echo "🌟 Starting FastAPI server on http://localhost:8000"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
