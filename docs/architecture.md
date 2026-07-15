# Architecture and versioning

The application has four boundaries:

1. `config` selects exactly one phase and resolves local paths.
2. `validation`, `codebook`, and `ingest` read immutable XLSX inputs. Blocking structure errors stop annotation; ingestion never sorts or repairs rows.
3. `models` calculates applicability and validates explicit answers independently of Streamlit. `app.py` renders the active row and obtains context only through the strict `utterance_order < focal_order` query.
4. `storage` writes current projections plus immutable snapshot events in one SQLite transaction. `export` joins coder-isolated projections back onto preserved source metadata and includes the complete event trail.

## Schema identity

The identity of directions is `(schema_version, SHA-256(codebook bytes))`. Startup registers the source filename and UTC time. Reusing a version with a different hash is an error; held-out also locks the active identity. Revisions append events under the schema used at save time, so a later schema never rewrites history.

## Unit state

An utterance progresses from absent to optional draft to submitted revision 1. A changed save after submission is revision 2 or later; unchanged navigation creates no event. A dispute becomes complete only when all its utterances are submitted and a separate dispute-level decision exists. The exported primary object is then propagated to submitted utterance rows without duplicating its stored decision.

Timing is wall-clock metadata, clamped nonnegative. It is intentionally not browser activity surveillance.
