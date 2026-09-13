import json
import time

import pandas as pd
from streamlit.testing.v1 import AppTest

from wikidisputes_ui.storage import Storage


def configured(monkeypatch, project):
    monkeypatch.setenv("WIKIDISPUTES_CONFIG", str(project.root / "project.toml"))
    (project.root / "project.toml").write_text(
        f'schema_sheet="Core_Schema"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\n'
        f'low_confidence_threshold=2\ngold_path="{project.gold_path}"\n'
        f'codebook_path="{project.codebook_path}"\ndatabase_path="{project.database_path}"\n'
        'export_directory="exports"\n'
    )
    return AppTest.from_file("app.py", default_timeout=10).run()


def enter(app):
    assert not app.exception, [item.value for item in app.exception]
    assert app.title, [item.value for item in app.error]
    if app.title[0].value == "WikiDisputes annotation":
        app.text_input[0].input("coder_01")
        app = next(b for b in app.button if b.label == "Continue").click().run()
    return next(b for b in app.button if b.label == "Resume annotation").click().run()


def radio(app, label):
    return next(item for item in app.radio if item.label == label)


def current_payload(**changes):
    payload = {
        "KS_present": 0,
        "KS_explicit_reasoning": None,
        "KS_grounding": None,
        "KS_new_evidence": None,
        "KS_restaking": None,
        "KS_bounding": None,
        "KI_present": 0,
        "C_off_topic_shift": 0,
        "C_interpersonal_attack_or_disrespect": 0,
        "C_formal_governance_action": 0,
        "malformed_utterance": False,
        "coder_confidence": 3,
        "review_flag": 0,
        "coder_notes": None,
    }
    payload.update(changes)
    return payload


def save_payload(storage, payload, *, uid="u1", schema_hash="old-hash"):
    storage.set_active_coder("coder_01")
    storage.save_utterance(
        coder="coder_01",
        utterance_id=uid,
        dispute_id="D1",
        payload=payload,
        answered_fields=set(payload),
        submit=True,
        schema_version="old-schema",
        schema_hash=schema_hash,
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )


def answer_all(app, ks=0, ki=0):
    radio(app, "Does this utterance stake knowledge?").set_value(ks)
    app = app.run()
    if ks:
        for label in (
            "Does it make its reasoning explicit?",
            "Does it ground its position?",
            "Does it restate an earlier position?",
            "Does it bound the claim?",
        ):
            radio(app, label).set_value(0)
    radio(app, "Does this utterance integrate knowledge?").set_value(ki)
    app = app.run()
    for label in (
        "Does this shift off topic?",
        "Does this attack or disrespect a contributor?",
        "Does this invoke formal governance?",
    ):
        radio(app, label).set_value(0)
    radio(app, "How confident are you in this utterance annotation?").set_value(3)
    radio(app, "Flag this utterance for review?").set_value(0)
    return app


def test_inline_workflow_has_no_stages_and_conditional_children(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    labels = {item.label for item in app.radio}
    assert "Does it make its reasoning explicit?" not in labels
    radio(app, "Does this utterance stake knowledge?").set_value(1)
    radio(app, "Does this utterance integrate knowledge?").set_value(1)
    app = app.run()
    labels = {item.label for item in app.radio}
    assert len(set(KS_CHILD_LABELS) & labels) == 4
    assert "Does it introduce new evidence?" not in labels
    assert not set(OBSOLETE_KI_CHILD_LABELS) & labels
    rendered = " ".join(str(m.value) for m in app.markdown)
    assert "Stage 1" not in rendered and "Stage 2" not in rendered and "Continue to details" not in rendered
    assert len([item for item in app.text_area if item.label == "Optional comment"]) == 1


def test_question_text_is_loaded_from_workbook(monkeypatch, synthetic_project):
    frame = pd.read_excel(synthetic_project.codebook_path, sheet_name="Core_Schema")
    frame.loc[frame.Label == "KS_present", "Question"] = "Workbook-specific KS wording?"
    with pd.ExcelWriter(synthetic_project.codebook_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Core_Schema", index=False)
    app = enter(configured(monkeypatch, synthetic_project))
    labels = {item.label for item in app.radio}
    assert "Workbook-specific KS wording?" in labels
    assert "Does this utterance stake knowledge?" not in labels


def test_question_only_hash_change_does_not_reset_progress(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    save_payload(storage, current_payload(), schema_hash="older-question-hash")
    app = configured(monkeypatch, synthetic_project)
    assert app.metric[0].value == "1 / 2"
    dispute = next(item for item in app.selectbox if item.label == "Article / dispute")
    dispute.set_value(dispute.options[0])
    app = app.run()
    utterance = next(item for item in app.selectbox if item.label == "Utterance")
    assert any("Submitted" in option and option.startswith("#2") for option in utterance.options)


def test_old_payload_is_incomplete_but_surviving_fields_prepopulate(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    save_payload(
        storage,
        {
            "KS_present": 1,
            "KS_claim_present": 1,
            "KS_evidence_reference": 0,
            "KS_reasoning": 1,
            "KS_restaking": 0,
            "KI_present": 1,
            "C_off_topic_shift": 0,
            "C_interpersonal_attack_or_disrespect": 0,
            "C_formal_governance_action": 0,
            "coder_confidence": 3,
            "review_flag": 0,
        },
    )
    app = configured(monkeypatch, synthetic_project)
    assert app.metric[0].value == "0 / 2"
    app = next(button for button in app.button if button.label == "Resume annotation").click().run()
    assert radio(app, "Does this utterance stake knowledge?").value == 1
    assert radio(app, "Does it restate an earlier position?").value == 0
    assert radio(app, "Does this utterance integrate knowledge?").value == 1


def test_obsolete_dispute_object_does_not_count_as_complete(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    save_payload(storage, current_payload(), uid="u1")
    save_payload(storage, current_payload(), uid="u2")
    storage.save_dispute(
        coder="coder_01",
        dispute_id="D1",
        payload={"C_primary_dispute_object": "wording_or_framing"},
        answered_fields={"C_primary_dispute_object"},
        schema_version="old-schema",
        schema_hash="old-hash",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    app = configured(monkeypatch, synthetic_project)
    dispute = next(item for item in app.selectbox if item.label == "Article / dispute")
    dispute.set_value(dispute.options[0])
    app = app.run()
    app = next(button for button in app.button if button.label == "Open dispute →").click().run()
    assert app.title[0].value == "Final dispute decision"


def test_valid_dispute_decision_waits_for_current_utterances(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    save_payload(storage, current_payload(), uid="u1")
    stale = current_payload()
    stale.pop("KS_new_evidence")
    save_payload(storage, stale, uid="u2")
    storage.save_dispute(
        coder="coder_01",
        dispute_id="D1",
        payload={"C_primary_dispute_object": "uncertain", "DV_dispute_resolution": 3},
        answered_fields={"C_primary_dispute_object", "DV_dispute_resolution"},
        schema_version="old-schema",
        schema_hash="old-hash",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    app = configured(monkeypatch, synthetic_project)
    assert [(item.label, item.value) for item in app.metric] == [
        ("Utterances submitted", "1 / 2"),
        ("Disputes finalized", "0 / 1"),
    ]
    dispute = next(item for item in app.selectbox if item.label == "Article / dispute")
    assert "In progress" in dispute.options[0]


def test_landing_and_annotation_navigation_target_specific_utterances(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    app = configured(monkeypatch, synthetic_project)

    dispute = next(item for item in app.selectbox if item.label == "Article / dispute")
    dispute.set_value(dispute.options[0])
    app = app.run()
    utterance = next(item for item in app.selectbox if item.label == "Utterance")
    utterance.set_value(next(option for option in utterance.options if option.startswith("#3")))
    app = app.run()
    app = next(button for button in app.button if button.label == "Open selected utterance →").click().run()

    assert app.session_state["unit_id"] == "u2"
    assert app.title[0].value == "Article"
    assert any("Dispute D1 · Utterance #3 · ID u2" in item.value for item in app.caption)
    rendered = " ".join(str(item.value) for item in app.markdown)
    assert "Replies to #2 · A · ID u1" in rendered

    target = next(item for item in app.selectbox if item.label == "Navigate to utterance")
    target.set_value(next(option for option in target.options if option.startswith("#2")))
    app = app.run()
    app = next(button for button in app.button if button.label == "Go to selected utterance →").click().run()
    assert app.session_state["unit_id"] == "u1"


KS_CHILD_LABELS = (
    "Does it make its reasoning explicit?",
    "Does it ground its position?",
    "Does it restate an earlier position?",
    "Does it bound the claim?",
)
OBSOLETE_KI_CHILD_LABELS = (
    "Does it ask others to assess, revise, or accept that edit?",
    "Does the edit visibly accommodate at least two positions or concerns?",
)


def test_parent_change_hides_and_clears_children(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    radio(app, "Does this utterance stake knowledge?").set_value(1)
    app = app.run()
    radio(app, KS_CHILD_LABELS[3]).set_value(1)
    radio(app, "Does this utterance stake knowledge?").set_value(0)
    app = app.run()
    assert not set(KS_CHILD_LABELS) & {item.label for item in app.radio}


def test_new_evidence_appears_only_after_grounding_yes(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    radio(app, "Does this utterance stake knowledge?").set_value(1)
    app = app.run()
    assert "Does it introduce new evidence?" not in {item.label for item in app.radio}
    radio(app, "Does it ground its position?").set_value(1)
    app = app.run()
    assert "Does it introduce new evidence?" in {item.label for item in app.radio}
    radio(app, "Does it ground its position?").set_value(0)
    app = app.run()
    assert "Does it introduce new evidence?" not in {item.label for item in app.radio}


def test_full_dispute_smoke_and_object_only_payload(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    app = answer_all(app)
    app = next(b for b in app.button if b.label == "Submit and next").click().run()
    assert app.session_state["unit_id"] == "u2"
    app = answer_all(app, ks=1, ki=1)
    app = next(b for b in app.button if b.label == "Submit and next").click().run()
    assert app.title[0].value == "Final dispute decision"
    first_opened_at = app.session_state["dispute_opened_at"]
    first_timer_start = app.session_state["dispute_timer_start"]
    workspace = configured(monkeypatch, synthetic_project)
    assert [(item.label, item.value) for item in workspace.metric] == [
        ("Utterances submitted", "2 / 2"),
        ("Disputes finalized", "0 / 1"),
    ]
    dispute = next(item for item in workspace.selectbox if item.label == "Article / dispute")
    assert "Final judgment pending" in dispute.options[0]
    assert [item.label for item in app.radio] == [
        "Which object primarily organizes this dispute?",
        "How resolved is this dispute?",
    ]
    assert app.radio[0].options == [
        "Claim or evidence validity",
        "Wording or representation",
        "Inclusion or weight",
        "Placement or structure",
        "Mixed",
        "Uncertain",
    ]
    app.radio[0].set_value("uncertain")
    app = next(b for b in app.button if b.label == "Complete dispute").click().run()
    assert app.title[0].value == "Final dispute decision"
    assert app.session_state["dispute_opened_at"] == first_opened_at
    assert app.session_state["dispute_timer_start"] == first_timer_start
    assert not Storage(synthetic_project.database_path).rows("dispute_annotations", "coder_01")
    app.session_state["dispute_timer_start"] = time.monotonic() - 5
    app.radio[1].set_value(3)
    app = next(b for b in app.button if b.label == "Complete dispute").click().run()
    row = Storage(synthetic_project.database_path).rows("dispute_annotations", "coder_01")[0]
    assert row["opened_at"] == first_opened_at
    assert row["elapsed_wall_seconds"] >= 5
    assert [(item.label, item.value) for item in app.metric] == [
        ("Utterances submitted", "2 / 2"),
        ("Disputes finalized", "1 / 1"),
    ]
    assert json.loads(row["payload_json"]) == {"C_primary_dispute_object": "uncertain", "DV_dispute_resolution": 3}
    assert json.loads(
        Storage(synthetic_project.database_path).rows("dispute_annotation_events", "coder_01")[0][
            "answered_fields_json"
        ]
    ) == ["C_primary_dispute_object", "DV_dispute_resolution"]


def test_annotator_remarks_are_isolated_by_utterance(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    app = answer_all(app)
    radio(app, "How confident are you in this utterance annotation?").set_value(5)
    radio(app, "Flag this utterance for review?").set_value(1)
    next(item for item in app.text_area if item.label == "Optional comment").input("Review u1")

    app = next(b for b in app.button if b.label == "Submit and next").click().run()

    assert app.session_state["unit_id"] == "u2"
    assert radio(app, "How confident are you in this utterance annotation?").value is None
    assert radio(app, "Flag this utterance for review?").value is None
    assert next(item for item in app.text_area if item.label == "Optional comment").value == ""


def test_malformed_utterance_can_submit_without_construct_labels(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    malformed = next(
        item for item in app.checkbox if item.label == "Malformed utterance / not reliably one speaker-turn"
    )
    app = malformed.check().run()
    assert "Does this utterance stake knowledge?" not in {item.label for item in app.radio}
    radio(app, "How confident are you in this utterance annotation?").set_value(3)
    radio(app, "Flag this utterance for review?").set_value(0)
    app = next(button for button in app.button if button.label == "Submit and next").click().run()
    saved = Storage(synthetic_project.database_path).current_utterance("coder_01", "u1")
    assert saved["status"] == "submitted"
    assert saved["payload"]["malformed_utterance"] is True


def test_earlier_conversation_shows_prior_ks_and_ki_labels(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    app = answer_all(app, ks=1, ki=0)
    app = next(button for button in app.button if button.label == "Submit and next").click().run()

    rendered = " ".join(str(item.value) for item in app.markdown)
    assert '<span class="badge">KS</span>' in rendered
    assert '<span class="badge">KI</span>' not in rendered
    assert "Context — not annotated" in rendered


def test_dispute_object_blocked_before_all_submissions(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    app = configured(monkeypatch, synthetic_project)
    app.session_state["page"] = "dispute"
    app.session_state["dispute_id"] = "D1"
    app = app.run()
    assert not any(item.label == "Which object primarily organizes this dispute?" for item in app.radio)
    assert any("Submit every substantive utterance" in item.value for item in app.error)


def test_prior_context_is_shown_but_future_utterances_are_hidden(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    rendered = " ".join(str(m.value) for m in app.markdown)
    assert "Earlier conversation" in [item.value for item in app.subheader]
    assert "Conversation heading" in rendered
    assert "Context — not annotated" in rendered
    assert "First proposal" in rendered
    assert '<div class="source-text">Reply</div>' not in rendered

    app = answer_all(app)
    next(b for b in app.button if b.label == "Submit and next").click().run()
    annotated_ids = {
        row["utterance_id"]
        for row in Storage(synthetic_project.database_path).rows("utterance_annotations", "coder_01")
    }
    assert annotated_ids == {"u1"}
