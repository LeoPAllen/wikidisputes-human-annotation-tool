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
sidebar exports only the active coder and active codebook hash.

## Schema and workflow

`data/source/codebook.xlsx` has exactly one authoritative worksheet, `Core_Schema`. Definitions, coding rules,
examples, provenance, and dispute-object option descriptions are read from it. The whole-file SHA-256 identifies the
active schema.

Each opened dispute uses one continuous utterance screen. Five always-applicable questions have explicit No/Yes
answers and no default. Answering Yes to KS reveals four inline KS questions; answering Yes to KI independently
reveals two inline KI questions. `KS_restaking` is entered by the coder from the visible earlier discussion and is not
derived. `KI_compromise_position` is binary. Changing either parent to No hides its children; normalized storage uses
null for those inapplicable answers.

Each utterance has exactly one required confidence response (1–5), one required review flag, and one optional comment.
After every substantive utterance in a dispute is submitted, the workflow shows only the final
`C_primary_dispute_object` decision. Its eight values and descriptions are parsed from the codebook coding rule.

The Excel export contains submitted substantive rows only. It propagates the dispute object to those rows, emits
inapplicable nulls as blank cells, uses nullable integers for binary/audit values, excludes legacy gold annotations and
obsolete schema fields, and retains source identifiers plus audit provenance. Historical SQLite event payloads remain
unchanged and available in database backups.

## Verification

```bash
.venv/bin/python -m wikidisputes_ui.validation
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Never edit either workbook under `data/source/`. Input QC reports source defects rather than repairing source rows.
