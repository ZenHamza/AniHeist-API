#!/bin/bash
# Start both the Consumet API server and our Python API locally for testing

echo "Starting Consumet API (Node.js) on port 3099..."
cd /home/kali/Desktop/consumet-local && node server.mjs &
CONSUMET_PID=$!
sleep 3
echo "Consumet API started (PID: $CONSUMET_PID)"

echo "Starting AniHeist API (Python) on port 8000..."
cd /home/kali/Desktop/Scacper && PYTHONPATH=/home/kali/Desktop/Scacper uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!
echo "API started (PID: $API_PID)"

echo ""
echo "======================================"
echo "  Consumet API: http://localhost:3099"
echo "  AniHeist API: http://localhost:8000"
echo "======================================"
echo "Press Ctrl+C to stop both servers"

trap "kill $CONSUMET_PID $API_PID 2>/dev/null" EXIT
wait
