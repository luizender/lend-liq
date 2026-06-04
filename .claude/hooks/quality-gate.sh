#!/bin/bash
# Stop hook: enforce the project's quality bar when Claude finishes a turn — ruff,
# the full test suite (100% coverage), and pylint (10.00/10). Exits 2 to hand any
# failure back to Claude to fix. Guards against re-entry loops via stop_hook_active.

cd "$CLAUDE_PROJECT_DIR" || exit 0

# If we already blocked once this turn, let Claude stop instead of looping.
if [[ "$(cat | python3 -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)" == "True" ]]; then
    exit 0
fi

venv="$CLAUDE_PROJECT_DIR/.venv/bin"
if out=$("$venv/ruff" check kamino_liq tests 2>&1) \
    && out=$("$venv/ruff" format --check kamino_liq tests 2>&1) \
    && out=$("$venv/pytest" -q --cov --cov-report=term-missing 2>&1) \
    && out=$("$venv/pylint" kamino_liq 2>&1); then
    exit 0
fi

echo "Quality gate failed — fix before finishing:" >&2
printf '%s\n' "$out" | tail -25 >&2
exit 2
