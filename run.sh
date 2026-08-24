#!/usr/bin/env bash
set -euo pipefail

# Activate the virtual environment from the project and run main.py
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$PROJECT_DIR/env/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "$PROJECT_DIR/env/bin/activate"
fi

# Ensure we run from the project directory so uvicorn can import `main:app`
cd "$PROJECT_DIR"

case "${1:-}" in
  serve|start)
    shift
    # Run the FastAPI app using uvicorn from the venv Python
    python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 "$@"
    ;;
  telegram|bot)
    shift
    python "$PROJECT_DIR/telegram_bot.py" "$@"
    ;;
  *)
    python "$PROJECT_DIR/main.py" "$@"
    ;;
esac
