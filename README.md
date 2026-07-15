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

## Share the app with annotators

This app is designed to run locally. Do not put one copy on a shared server: coder IDs are labels, not passwords, and a shared database would let coders switch into one another's records.

1. **Prepare the study copy.** Set the intended `phase`, `schema_locked`, and paths in `config/project.toml`. Run validation and the checks under [Verification](#verification). Resolve any blocking source-data issues before distribution.
2. **Make one clean copy per annotator.** Each copy must contain the repository files and the two unchanged workbooks in `data/source/`, but must not contain `.venv/`, an existing file in `data/local/`, prior `exports/`, or prior `reports/`. Give each copy a unique name, such as `wikidisputes_coder_01`, and send it through the study's approved private file-transfer channel. Never email source data unless the study protocol permits it.
3. **Assign an ID.** Privately give each annotator one pseudonymous ID, for example `coder_01`. IDs must be 3–40 characters and may contain letters, numbers, `_`, or `-`. Do not reuse an ID across annotators.
4. **Have the annotator install and start the app.** After extracting their copy, they run the commands below from its top-level directory, open the local URL printed by Streamlit (normally `http://localhost:8501`), and enter only their assigned ID.

   macOS/Linux:

   ```bash
   python3.11 -m venv .venv
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m wikidisputes_ui.validation
   .venv/bin/streamlit run app.py
   ```

   Windows PowerShell:

   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\python -m pip install --upgrade pip
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python -m wikidisputes_ui.validation
   .venv\Scripts\streamlit run app.py
   ```

5. **Save and back up work.** Annotation saves are written automatically to the SQLite file configured by `database_path`. At the end of every session, the annotator uses **Download database backup** and stores it securely. They should not edit the source workbooks, configuration, database, or exported files.
6. **Return the results.** When finished, the annotator downloads both **Export my annotations** (`.xlsx`) and **Download database backup** (`.sqlite3`) and returns both through the approved private channel. Keep each annotator's files in a separate folder, confirm the filenames contain the assigned ID, and preserve the returned database unchanged. Do not combine or overwrite coder databases; use the XLSX export for analysis and the SQLite backup for recovery and audit history.

If an annotator needs to resume on another computer, send that annotator's complete app copy with their latest SQLite backup placed at the configured `database_path`. The app and database should never be open on two computers at once.

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
