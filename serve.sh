#!/usr/bin/env bash
# Serve the local CLAM replica. Usage: ./serve.sh [port]
cd "$(dirname "$0")"
exec python3 serve.py "${1:-8000}"
