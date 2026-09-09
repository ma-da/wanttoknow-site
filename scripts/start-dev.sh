#!/usr/bin/env bash

set -e

PROJECT_ROOT="/mnt/c/datasources/wanttoknow-site"
BACKEND_ROOT="$PROJECT_ROOT/backend"
VENV="$HOME/.venvs/wanttoknow-site"

echo
echo "Starting WantToKnow.info development server..."
echo

if [ ! -f "$VENV/bin/activate" ]; then
    echo "ERROR: Python environment not found:"
    echo "$VENV"
    echo
    echo "Create it with:"
    echo "python3 -m venv $VENV"
    exit 1
fi

cd "$BACKEND_ROOT"

source "$VENV/bin/activate"

echo "Project: $PROJECT_ROOT"
echo "Python:  $(which python)"
echo
echo "Site:    http://localhost:8000/"
echo "Health:  http://localhost:8000/api/health"
echo
echo "Press Ctrl+C to stop."
echo

python -m uvicorn app.main:app \
    --reload \
    --host 127.0.0.1 \
    --port 8000