#!/bin/bash

# Hikvision Live Stream API - Run Script

set -e

echo "🚀 Starting Hikvision Live Stream API..."

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env 2>/dev/null || echo "Please create .env file with your configuration"
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python -m venv venv
fi

echo "🔧 Activating virtual environment..."
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🏃 Starting server..."
PORT="${PORT:-8335}"
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
