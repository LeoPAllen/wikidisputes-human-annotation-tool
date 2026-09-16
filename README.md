# WikiDisputes human annotation tool

A private, local Streamlit workflow for coding utterances from the `Gold_Annotation` worksheet in
`data/source/gold_input.xlsx`. `substantive_order` is the canonical display, context, and navigation sequence.
`utterance_order` is chronology metadata and may be null; Gold files may contain zero display-only context rows.

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
finalized dispute decision in both columns, emits inapplicable nulls as blank cells, uses nullable integers for
binary, resolution, and audit values, excludes legacy gold annotations and obsolete schema fields, and retains source
identifiers plus audit provenance. A `Dispute_Annotations` sheet has one row per dispute and includes the saved
dispute decision's own schema version/hash, save time, and revision number; disputes without a saved decision have
blank annotation fields. The sheet also records the dispute form's opening time and elapsed wall time, and an
a `decision_is_current` flag distinguishes structurally valid decisions from older or invalid saved values, while
`dispute_is_finalized` also requires every utterance in that dispute to be current. Dispute values appear on utterance
rows only when the dispute is finalized.
Historical SQLite event payloads remain unchanged and available in database backups.
Older utterance records missing `KS_new_evidence` require re-review; older dispute records missing a valid resolution
require completion. Existing event history is retained.

To update inputs, replace `data/source/gold_input.xlsx` and/or `data/source/codebook.xlsx`, then restart Streamlit.

Annotations follow the Gold stable utterance key. Gold reconciliation compares each focal utterance and its ordered
visible prior coding context. If that context is unchanged, an existing submitted annotation remains current. If focal
text or prior visible context changes because of source edits or reordering, the existing answers are retained but the
current annotation is marked `needs_rereview` and must be reviewed and submitted again. Newly annotatable rows enter
the normal annotation queue.

When a Gold change affects a dispute's coding context, its current dispute-level decision may be invalidated while
append-only annotation event history is retained. Gold reconciliation creates a SQLite backup before mutating current
annotation state.

Coders may mark a unit “Malformed utterance / not reliably one speaker-turn”; construct labels then become optional,
existing answers are retained, and the unit remains in the queue and export.

## Verification

```bash
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Never edit either workbook under `data/source/`. Input QC reports source defects rather than repairing source rows.
