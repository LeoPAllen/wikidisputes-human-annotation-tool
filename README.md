# WikiDisputes human annotation tool

A private, local Streamlit workflow for coding the single `Gold_Annotation` worksheet in `data/source/gold_input.xlsx`. All 438 source rows are retained; 404 `utterance` rows are annotatable and 34 `context` rows are display-only conversation headings.

## Setup and run

Python 3.11+ is required. On macOS/Linux:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/streamlit run app.py
```

On Windows PowerShell, use `.venv\Scripts\python.exe`, `.venv\Scripts\pip.exe`, and `.venv\Scripts\streamlit.exe` in the equivalent commands.

The first screen asks for a pseudonymous coder ID. It identifies local records; it is not authentication. Give each coder a separate repository/database copy, or at minimum a distinct `database_path`. Use the sidebar to export the active coder's workbook or download a consistent SQLite backup.

## Data and schema

`config/project.toml` names `annotation_sheet = "Gold_Annotation"`, schema `0.9.7`, and `Core_Schema_SIMPLIFIED`. Do not edit either source XLSX. The simplified schema and its controlled-value sheets are authoritative.

Codebook evolution is tracked independently of the dataset by `schema_version` plus the SHA-256 of the complete codebook. If the codebook changes, increment `schema_version`; reusing a registered version with a different hash fails closed. `schema_locked` is an optional administrative freeze and is normally `false` during annotation.

## Research workflow

Before distributing a study copy, run validation and all checks below. Back up the SQLite file regularly. Exports contain `Gold_Annotations`, coder-specific current dispute decisions and event histories, registered schema versions, and the QC report. Context rows remain in source order and have blank utterance annotation/provenance fields.

Each utterance is coded in two local stages. The first records the four KS, KI, hostility, and formal-escalation gateway judgments as a durable draft. The second shows only details and evidence that apply, followed by confidence and review. Reopening a draft with all gateways answered resumes at the detail stage; the same utterance timer and append-only event history are retained.

The reading pane shows the source section heading once, the focal utterance, and strictly earlier substantive turns. Source text is escaped and rendered with its original whitespace. Raw IDs remain available in the collapsed source details rather than dominating the reading surface.

Coder-facing hiding of `escalated`, outcomes, administrative sampling fields, `dispute_resolution_url`, `Dispute_Rationales`, and `Validation_Audit` is UI blinding, not filesystem access control. The master XLSX still contains administrative data. Hard blinding requires distributing a separately sanitized workbook/repository.

## Verification and troubleshooting

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m wikidisputes_ui.validation
```

- Missing sheet or columns: restore the authoritative `Gold_Annotation` worksheet; do not repair rows in application code.
- Codebook hash mismatch: increment `schema_version` after the directions change.
- Legacy database collision: migration stops before changes and identifies the colliding coder/unit records. Reconcile or archive them in a copy, then retry.
- Timing is best-effort wall time for an opened screen; it is not active-attention tracking.
