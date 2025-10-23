#!/bin/bash
cd "$(dirname "$0")"
if [ -d ".venv" ]; then
  source ".venv/bin/activate"
fi
python3 business_card_scanner.py
read -p "Press any key to close..."