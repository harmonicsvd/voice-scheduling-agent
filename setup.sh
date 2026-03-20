#!/bin/bash

echo "🎙️ Voice Scheduling Agent — Local Setup"
echo "========================================"

if ! command -v conda &> /dev/null; then
    echo "❌ conda not found. Please install Miniconda first:"
    echo "   https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "❌ .env file not found."
    echo "   Copy example.env to .env and fill in your credentials:"
    echo "   cp example.env .env"
    echo ""
    exit 1
fi

echo "✅ Creating conda environment..."
conda create -n voice-scheduler-agent python=3.12 -y

echo "✅ Activating environment..."
eval "$(conda shell.bash hook)"
conda activate voice-scheduler-agent

echo "✅ Installing dependencies..."
pip install -r requirements.txt

echo "✅ Starting backend server..."
echo ""
echo "========================================"
echo "✅ Backend running at http://127.0.0.1:8000"
echo "⚠️  VAPI webhook needs a public URL."
echo "   Use ngrok: ngrok http 8000"
echo "   Then update webhook URL in VAPI dashboard"
echo "👉 Open index.html in your browser"
echo "========================================"
echo ""

uvicorn app.main:app --reload