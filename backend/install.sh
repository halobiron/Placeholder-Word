#!/bin/bash
# Fix: Install with system Python 3.9 instead of miniconda Python 3.13

echo "🔧 Fixing lxml installation issue..."
echo "System Python: $(python3 --version)"
echo "Miniconda Python: $(~/miniconda3/bin/python --version)"

echo ""
echo "📦 Installing with system Python 3.9..."
cd backend

# Use system python3 explicitly
python3 -m pip install -r requirements.txt

echo ""
echo "✅ Done! Check installation:"
python3 -m pip list | grep -E "fastapi|lxml|docx"

echo ""
echo "🚀 Start backend với:"
echo "  cd backend"
echo "  python3 -m uvicorn main:app --reload --port 8000"
