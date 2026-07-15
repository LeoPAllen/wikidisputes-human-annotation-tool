# WikiDisputes human annotation tool

A private, local Streamlit application for sequential KS/KI annotation. Each coder must receive a separate repository copy, or at minimum a separate `database_path` in `config/project.toml`. Coder IDs identify local records; they do not authenticate users.

## Setup and validation

Python 3.11 or newer is required. The two files in `data/source/` are immutable inputs.

macOS/Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/streamlit run app.py
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m wikidisputes_ui.validation
.venv\Scripts\streamlit run app.py
```

Validation writes `reports/input_qc.md`. Blocking errors deliberately prevent the UI from opening annotation data; the program never repairs, reorders, or rewrites a source workbook.

## Workflow

Enter the assigned pseudonymous coder ID, resume the next sequential utterance, and explicitly answer every applicable field. Drafts may be incomplete. Submission enforces dependencies, null semantics, evidence, and justification rules. Only prior turns are visible. Once every utterance in a dispute is submitted, the separate dispute screen reveals the whole discussion and collects its primary object. `Review completed` permits revisions while preserving append-only history and the original no-future context boundary.

The sidebar provides:

- **Export my annotations**: an auditable XLSX containing current state, events, schema registrations, and QC;
- **Download database backup**: a consistent SQLite snapshot;
- **Switch coder**: an explicit, warned identity change.

Downloaded exports are browser downloads. Programmatic exports can also be written with `wikidisputes_ui.export.write_export` to the configured `export_directory`.

## Calibration to held-out transition

Start with `phase = "calibration"` and `schema_locked = false`. Only `3_Calibration_Coder` is exposed. After calibration is reconciled and the directions are frozen, give any changed codebook a new schema version, then set:

```toml
phase = "heldout"
schema_locked = true
```

Held-out mode refuses to start without the lock and rejects version/hash drift. It exposes only `4_Heldout_Coder`. Existing events retain their original schema version and hash.

## Verification

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m wikidisputes_ui.validation
```

PowerShell uses the same commands with `.venv\Scripts\` instead of `.venv/bin/`.

## Troubleshooting

- **Missing partition sheets:** the input must contain `3_Calibration_Coder` and `4_Heldout_Coder`; do not infer partitions from an administrative master sheet.
- **Schema hash drift:** change `schema_version` when directions change. Never replace a registered workbook under the same version.
- **Resetting a local test copy:** stop Streamlit and move the configured SQLite database aside. Never share or merge databases between coders.
- **Refresh timing:** elapsed time is best-effort wall time from opening to saving. Refresh or restart begins a conservative new attempt; it is not active-attention tracking.
- **Port already used:** launch with `streamlit run app.py --server.port 8502`.

## Privacy and scope

The app is local: no telemetry, APIs, cloud storage, model assistance, or authentication service. Administrative sampling fields and escalation outcomes are neither rendered nor used for coder-facing decisions.
