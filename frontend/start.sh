#!/bin/bash
# Mail Merge Placeholder System - Frontend Startup Script

echo "🚀 Starting Mail Merge Placeholder System Frontend..."

# Check Node.js version
node_version=$(node --version 2>&1)
echo "✓ Node version: $node_version"

# Install dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
else
    echo "✓ Dependencies already installed"
fi

# Start dev server
echo "🌟 Starting Vite dev server on http://localhost:5173"
npm run dev
