# Copilot Instructions

## Short UI Test Rule
- For any UI-related change, add or update a short, targeted Playwright test in `tools/ui_smoke_test.py` guarded by a new CLI flag (e.g. `--hotkey-only`).
- The short test must only cover the changed UI behavior (2-5 steps) and run quickly.
- After implementing UI changes, run the short test with the venv Python.
- Run the full smoke test only when explicitly requested.

## Command Template
C:/Data/Source/pdf-paraparatrans2/.venv/Scripts/python.exe tools/ui_smoke_test.py --start-server --headless --port 5079 --<feature>-only
