#!/bin/bash
# Compatibility entry point; the descriptive launcher owns startup behavior.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$PROJECT_DIR/run_prototype (Start Application).sh" "$@"
