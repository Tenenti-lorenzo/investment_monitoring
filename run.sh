#!/bin/bash
cd "$(dirname "$0")"
echo "🚀 PortfolioLab avviato su http://localhost:8000"
uvicorn backend.main:app --reload --port 8000
