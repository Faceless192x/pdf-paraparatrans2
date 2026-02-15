# Testing Rules (Short UI Tests)

## Purpose
Use short, targeted UI tests after each UI-related change instead of running the full smoke test every time.

## Rule Summary
1. For any UI change, add or update a short test in `tools/ui_smoke_test.py` guarded by a new CLI flag.
2. The short test should only exercise the changed UI behavior (2-5 steps).
3. Keep it fast: avoid full navigation beyond what is necessary.
4. Run the short test after changes. Run the full smoke test only when needed.

## Example Pattern
- Add a flag: `--hotkey-only`.
- In the test runner, when the flag is set, skip unrelated checks and only run the new section.

## Suggested CLI Convention
- `--hotkey-only`, `--toc-only`, `--dict-only`, etc.

## Command Template
- Use the venv Python:
  `C:/Data/Source/pdf-paraparatrans2/.venv/Scripts/python.exe tools/ui_smoke_test.py --start-server --headless --port 5079 --hotkey-only`
