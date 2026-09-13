# WikiDisputes human annotation tool

A private, local Streamlit workflow for coding substantive utterances from the `Gold_Annotation` worksheet in
`data/source/gold_input.xlsx`. Context rows are display-only and source order is preserved.

## Setup and run

Python 3.11+ is required:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/streamlit run app.py
```

The first screen requests a pseudonymous coder ID. SQLite projections and append-only events are coder-isolated. The
sidebar exports only the active coder.

## Schema and workflow

`data/source/codebook.xlsx` has exactly one authoritative worksheet, `Core_Schema`. Questions, definitions, coding
rules, examples, provenance, and dispute-object values/descriptions are read from it, including the exact `Question`
column. The whole-file SHA-256 remains audit metadata, while structural payload compatibility controls progress and
export.

Each opened dispute uses one continuous utterance screen. Five always-applicable questions have explicit No/Yes
answers and no default. Answering Yes to KS reveals its inline KS questions; `KS_new_evidence` is required only when
`KS_grounding` is Yes. KI is a standalone, independent field.
`KS_restaking` is entered by the coder from the visible earlier discussion and is not derived. Changing KS to No hides
its children; normalized storage uses null for those inapplicable answers.

Each utterance has exactly one required confidence response (1–5), one required review flag, and one optional comment.
After every substantive utterance in a dispute is submitted, the workflow shows the final
`C_primary_dispute_object` and `DV_dispute_resolution` decisions. Both are required; resolution is an integer from 1
through 5. Dispute-object values come from the codebook Indicator enum; matching descriptions are parsed from the
coding rule when present.
The workspace shows separate submitted-utterance and finalized-dispute counts. A dispute is finalized only when all
its utterances are current and its final decision has both valid answers.

The Excel export contains only submitted substantive rows with all current utterance schema keys. It propagates only a
current-valid dispute decision in both columns, emits inapplicable nulls as blank cells, uses nullable integers for
binary, resolution, and audit values, excludes legacy gold annotations and obsolete schema fields, and retains source
identifiers plus audit provenance. A `Dispute_Annotations` sheet has one row per dispute and includes the saved
dispute decision's own schema version/hash, save time, and revision number; disputes without a saved decision have
blank annotation fields.
Historical SQLite event payloads remain unchanged and available in database backups.
Older utterance records missing `KS_new_evidence` require re-review; older dispute records missing a valid resolution
require completion. Existing event history is retained.

To update inputs, replace `data/source/gold_input.xlsx` and/or `data/source/codebook.xlsx`, then restart Streamlit.
Annotations follow the Gold stable utterance key, so source edits and reordering do not reset SQLite. Coders may mark a
substantive unit “Malformed utterance / not reliably one speaker-turn”; construct labels then become optional, existing
answers are retained, and the unit remains in the queue and export.

## Verification

```bash
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Never edit either workbook under `data/source/`. Input QC reports source defects rather than repairing source rows.
