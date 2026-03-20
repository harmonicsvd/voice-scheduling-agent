#!/bin/bash

echo "🎙️ Voice Scheduling Agent — Local Setup"
echo "========================================"

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "❌ conda not found. Please install Miniconda first:"
    echo "   https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found."
    echo "   Please create a .env file with the following:"
    echo ""
    echo "   CALENDAR_ID=your-gmail@gmail.com"
    echo "   SERVICE_ACCOUNT_JSON={...your service account json...}"
    echo "   VAPI_PUBLIC_KEY=your-vapi-public-key"
    echo ""
    exit 1
fi

echo "✅ Creating conda environment..."
conda create -n voice-scheduler-agent python=3.12 -y

echo "✅ Activating environment..."
source activate voice-scheduler-agent

echo "✅ Installing dependencies..."
pip install -r requirements.txt

echo "✅ Starting backend server..."
echo ""
echo "========================================"
echo "✅ Backend running at http://127.0.0.1:8000"
echo "👉 Now open index.html in your browser"
echo "========================================"
echo ""

uvicorn app.main:app --reload