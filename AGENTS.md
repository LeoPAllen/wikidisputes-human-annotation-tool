# Repository instructions

## Layout

- `app.py`: Streamlit composition only.
- `wikidisputes_ui/`: configuration, authoritative codebook parsing, ingestion, validation, rules, SQLite storage, export, and UI helpers.
- `config/project.toml`: unified annotation sheet, schema, and local paths.
- `data/source/*.xlsx`: immutable researcher inputs.
- `data/local/`, `exports/`, `reports/`: generated local artifacts.
- `tests/`: small synthetic conversations and focused unit/AppTest coverage.
- `docs/architecture.md`: data flow and versioning invariants.

## Commands

Use Python 3.11+ from `.venv`:

```bash
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/streamlit run app.py
```

## Conventions and invariants

- Never modify `data/source/codebook.xlsx` or `data/source/gold_input.xlsx`.
- The simplified codebook sheet and controlled-value sheets are authoritative; do not copy definitions into Python.
- Preserve source order. Do not repair, deduplicate, truncate, or silently normalize source rows.
- Context for utterance `t` is strictly the same dispute's rows with lower `utterance_order`, including during revision.
- Store inapplicability only as JSON/SQL null and export it as a blank cell.
- Do not preselect substantive UI choices. Deliberately answered null feedback must remain distinguishable via `answered_fields`.
- Current tables are projections; event tables are append-only. Every saved event carries coder, schema version/hash, UTC timestamps, elapsed wall time, and application version.
- `schema_locked` is an optional administrative freeze, independent of ordinary annotation. Never expose administrative or escalation fields to coders.
- Keep dependencies small and tests synthetic.

## Definition of done

A change is complete only after validation, pytest, Ruff lint, Ruff format check, and a Streamlit/AppTest smoke run pass; the rendered workflow and diff are reviewed; source workbook hashes are unchanged; and QC blockers are reported as source-data issues rather than bypassed.
