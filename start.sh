#!/usr/bin/env bash
# Convenience entry: start main RGEE + RGEE_Analysis_Agent together.
exec "$(cd "$(dirname "$0")" && pwd)/scripts/start_project.sh" "$@"
