---
name: regen-dbc
description: Regenerate all DBC-derived code locally (C decoders, lart_msgs, dashboard API, C++ bridge), run the DBC tests, and summarise the generated diff — the same flow regenerate-dbcs.yml runs in CI.
disable-model-invocation: true
argument-hint: "[--source-dir /path/to/T26_DBC]"
---

Run from the repository root. Stop at the first failing step and report the failure; do not continue or work around it.

1. Initialise submodules (`src/lart_msgs` receives generated messages):
   ```bash
   git submodule update --init --recursive
   ```

2. Create the pinned DBC venv if missing (versions in `scripts/requirements-dbc.txt` match CI):
   ```bash
   test -x /tmp/dbc-venv/bin/python || python3 -m venv /tmp/dbc-venv
   /tmp/dbc-venv/bin/pip install -q -r scripts/requirements-dbc.txt
   ```

3. Regenerate. Pass `$ARGUMENTS` through (e.g. `--source-dir /tmp/t26-dbc` for an upstream checkout):
   ```bash
   /tmp/dbc-venv/bin/python scripts/regenerate_dbcs.py $ARGUMENTS
   ```
   If validation fails, report the error verbatim. Never bypass strict validation or guess a wire layout.

4. Run the DBC tests (same set as `validate-dbc-arm64.yml`), then whitespace checks:
   ```bash
   /tmp/dbc-venv/bin/python -m pytest -q tests/test_regenerate_dbcs.py tests/test_dbc_generation.py tests/test_dbc_api_abi.py tests/test_dbc_decoding.py tests/test_dbc_sync_workflow.py
   git diff --check
   git -C src/lart_msgs diff --check
   ```

5. Summarise the generated output:
   ```bash
   git diff --stat
   git -C src/lart_msgs diff --stat
   ```

Report: whether regeneration and tests passed, the diff stats for both repos, and which consumer updates the change needs according to the table in `docs/DBC-Update-Guide.md` (added/removed/renamed signals, scale/offset changes, enum changes). Do not edit generated files, commit, or push.
