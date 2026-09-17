#!/bin/bash
# Avvia Ink Monitor su porta 8081
cd "$(dirname "$0")"

pkill -f "main.py --port 8081" 2>/dev/null
sleep 0.5

echo "Avvio Ink Monitor..."
python3 main.py --port 8081
