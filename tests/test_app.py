from pathlib import Path
import re

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest
import pytest

from wikidisputes_ui.codebook import load_codebook, schema_id
from wikidisputes_ui.storage import Storage


GATEWAYS = {
    "Knowledge staking (KS)",
    "Knowledge integration (KI)",
    "Off-topic shift",
    "Interpersonal attack or disrespect",
    "Formal governance action",
}


def configured_app(monkeypatch, synthetic_project):
    st.cache_resource.clear()
    config = synthetic_project.root / "project.toml"
    config.write_text(
        f'''schema_sheet="Core_Schema_SIMPLIFIED"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\nlow_confidence_threshold=2\ngold_path="{synthetic_project.gold_path}"\ncodebook_path="{synthetic_project.codebook_path}"\ndatabase_path="{synthetic_project.database_path}"\nexport_directory="{synthetic_project.export_directory}"\n'''
    )
    monkeypatch.setenv("WIKIDISPUTES_CONFIG", str(config))
    return AppTest.from_file(str(Path("app.py").resolve()), default_timeout=10).run()


def enter_first_utterance(app):
    if app.title[0].value == "WikiDisputes annotation":
        app.text_input[0].input("coder_01")
        app = next(button for button in app.button if button.label == "Continue").click().run()
    return next(button for button in app.button if button.label == "Resume annotation").click().run()


def set_gateways(app, **values):
    defaults = dict.fromkeys(GATEWAYS, 0)
    defaults.update(values)
    for radio in app.radio:
        if radio.label in defaults:
            radio.set_value(defaults[radio.label])
    return app


def task_titles(app):
    titles = []
    for element in app.markdown:
        match = re.fullmatch(r'<div class="task-heading">(\d+)\. (.+)</div>', str(element.value))
        if match:
            titles.append((int(match.group(1)), match.group(2)))
    return titles


def submit_first_utterance_all_negative(app):
    app = set_gateways(app)
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    # AppTest retains the preceding stage's element tree for one interaction.
    for field in (
        "KS_present",
        "KI_present",
        "C_off_topic_shift",
        "C_interpersonal_attack_or_disrespect",
        "C_formal_governance_action",
    ):
        app.session_state[f"gateway_{field}_u1"] = 0
    next(radio for radio in app.radio if radio.label == "Coder confidence").set_value(5)
    next(radio for radio in app.radio if radio.label == "Flag for review").set_value(0)
    app = app.run()
    return next(button for button in app.button if button.label == "Submit and next").click().run()


def save_submitted(storage, book, uid, did):
    storage.save_utterance(
        coder="coder_01",
        utterance_id=uid,
        dispute_id=did,
        payload={"KS_present": 0},
        answered_fields={"KS_present"},
        submit=True,
        schema_version=schema_id(book.file_hash),
        schema_hash=book.file_hash,
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )


def test_new_utterance_stage_one_and_reading_hierarchy(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    assert not app.exception
    assert {radio.label for radio in app.radio} == GATEWAYS
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert rendered.count("Conversation heading") == 1
    assert "First proposal" in rendered
    assert "Current utterance" in rendered
    assert "max-width: 78ch" in rendered and "white-space: pre-wrap" in rendered
    assert "background: var(--secondary-background-color)" in rendered
    assert "Dispute D1" not in rendered and "ID u1" not in rendered
    assert "Code Yes when the utterance asserts or challenges substantive knowledge" in rendered
    assert "Code 1 when the utterance asserts or challenges substantive knowledge" not in rendered
    blinded = ("escalated", "dispute_resolution_url", "validation_audit", "sampling", "outcome")
    assert not any(name in rendered.casefold() for name in blinded)
    assert not any(label in {radio.label for radio in app.radio} for label in ("Coder confidence", "Flag for review"))
    assert [field.label for field in app.text_input if field.label == "Optional coder note"] == ["Optional coder note"]
    note = next(field for field in app.text_input if field.label == "Optional coder note")
    assert note.placeholder == "Write an optional note here"
    assert task_titles(app) == [
        (1, "Knowledge staking (KS)"),
        (2, "Knowledge integration (KI)"),
        (3, "Off-topic shift"),
        (4, "Interpersonal attack or disrespect"),
        (5, "Formal governance action"),
        (6, "Add an optional note"),
    ]
    assert sum(expander.label == "Coding guidance" for expander in app.expander) == 5

    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    assert len(app.error) == 5
    assert all("before continuing" in error.value for error in app.error)


def test_all_negative_stage_two_and_draft_reload(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app)
    opened_at = app.session_state["utterance_opened_at"]
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    assert not app.exception
    assert app.session_state["utterance_opened_at"] == opened_at
    assert any("No detailed fields apply" in info.value for info in app.info)
    labels = {radio.label for radio in app.radio}
    assert {"Coder confidence", "Flag for review"} <= labels
    assert not labels & {"Shares supporting evidence", "Proposes an edit"}
    assert any(button.label == "Change presence answers" for button in app.button)
    assert not any("Not applicable" in str(markdown.value) for markdown in app.markdown)

    reloaded = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    assert any("No detailed fields apply" in info.value for info in reloaded.info)
    assert {"Coder confidence", "Flag for review"} <= {radio.label for radio in reloaded.radio}


def test_low_confidence_allows_optional_notes_and_submission(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app)
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    confidence = next(radio for radio in app.radio if radio.label == "Coder confidence")
    review = next(radio for radio in app.radio if radio.label == "Flag for review")
    confidence.set_value(2)
    review.set_value(0)
    app = app.run()
    assert [field.label for field in app.text_input].count("Optional coder note") == 1
    assert not any(area.label == "Short justification" for area in app.text_area)
    app = next(button for button in app.button if button.label == "Submit and next").click().run()
    assert {radio.label for radio in app.radio} == GATEWAYS
    assert app.session_state["annotation_stage"] == 1


def test_coder_notes_explain_when_they_are_recorded(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app)
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))

    next(field for field in app.text_input if field.label == "Optional coder note").input("Check context")
    app = app.run()
    assert any("Coder note entered" in caption.value for caption in app.caption)
    app = next(button for button in app.button if button.label == "Save draft").click().run()
    assert any("Draft saved" in success.value for success in app.success)

    reloaded = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    notes = next(field for field in reloaded.text_input if field.label == "Optional coder note")
    assert notes.value == "Check context"


@pytest.mark.parametrize(
    ("positives", "present", "absent"),
    [
        (
            {"Knowledge staking (KS)": 1},
            {"Shares supporting evidence"},
            {"Proposes an edit", "KI evidence span", "Control evidence span"},
        ),
        (
            {"Knowledge integration (KI)": 1},
            {"Proposes an edit", "Solicits feedback", "KI evidence span"},
            {"Shares supporting evidence", "Control evidence span"},
        ),
        (
            {"Interpersonal attack or disrespect": 1},
            {"Control evidence span"},
            {"Shares supporting evidence", "Proposes an edit", "KI evidence span"},
        ),
        (
            {"Knowledge staking (KS)": 1, "Knowledge integration (KI)": 1, "Formal governance action": 1},
            {
                "Shares supporting evidence",
                "Proposes an edit",
                "Solicits feedback",
                "KI evidence span",
                "Control evidence span",
            },
            set(),
        ),
    ],
)
def test_stage_two_renders_only_applicable_families(monkeypatch, synthetic_project, positives, present, absent):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app, **positives)
    next(button for button in app.button if button.label == "Continue to details").click().run()
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    labels = {radio.label for radio in app.radio} | {area.label for area in app.text_area}
    assert present <= labels
    assert not absent & labels
    assert "KS evidence span" not in labels
    assert "Explicit feedback on an earlier proposed or enacted edit" not in labels
    visible_text = " ".join(
        [item.value for item in app.markdown]
        + [item.value for item in app.caption]
        + [widget.label for widget in [*app.radio, *app.text_area, *app.multiselect, *app.selectbox]]
    )
    assert "candidate" not in visible_text.lower()


def test_evidence_guidance_precedes_distinct_multiselect_task(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app, **{"Knowledge staking (KS)": 1})
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    next(radio for radio in app.radio if radio.label == "Shares supporting evidence").set_value(1)
    app = app.run()
    titles = task_titles(app)
    assert [number for number, _ in titles] == list(range(1, len(titles) + 1))
    assert any(label == "Which evidence type or types are present?" for _, label in titles)
    evidence = next(select for select in app.multiselect if select.label == "Evidence types present")
    book = load_codebook(synthetic_project.codebook_path)
    assert set(evidence.options) == set(book.evidence_types)
    assert any(expander.label == "Evidence-type definitions" for expander in app.expander)
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert "Controlled-value definitions" in rendered
    assert all(guide["Definition"] in rendered for guide in book.evidence_types.values())


def test_previous_navigation_saves_edits_as_draft_without_submission(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = submit_first_utterance_all_negative(app)
    assert app.session_state["unit_id"] == "u2"
    next(radio for radio in app.radio if radio.label == "Knowledge staking (KS)").set_value(1)
    app = next(button for button in app.button if button.label == "← Previous utterance").click().run()
    assert app.session_state["unit_id"] == "u1"
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert "First proposal" in rendered
    assert '<div class="source-text">Reply</div>' not in rendered
    storage = Storage(synthetic_project.database_path)
    draft = storage.current_utterance("coder_01", "u2")
    assert draft["status"] == "draft"
    assert draft["payload"]["KS_present"] == 1
    events = [row for row in storage.rows("utterance_annotation_events", "coder_01") if row["utterance_id"] == "u2"]
    assert [event["event_type"] for event in events] == ["draft"]


def test_navigation_without_answers_creates_no_spurious_draft(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = submit_first_utterance_all_negative(app)
    app = next(button for button in app.button if button.label == "← Previous utterance").click().run()
    assert app.session_state["unit_id"] == "u1"
    storage = Storage(synthetic_project.database_path)
    assert storage.current_utterance("coder_01", "u2") is None


def test_dispute_navigation_opens_earliest_unsubmitted_even_when_later_is_submitted(
    monkeypatch, synthetic_project, source_rows
):
    second = source_rows.copy()
    second["dispute_sequence"] = 2
    second["dispute_id"] = "D2"
    second["utterance_id"] = ["ctx2", "d2u1", "d2u2"]
    second["reply_to_utterance_id"] = [None, None, "d2u1"]
    second["utterance_text"] = ["Second heading", "D2 first", "D2 later"]
    combined = pd.concat([source_rows, second], ignore_index=True)
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    book = load_codebook(synthetic_project.codebook_path)
    save_submitted(storage, book, "d2u2", "D2")
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    selector = next(select for select in app.selectbox if select.label == "Move to another dispute")
    d2_label = next(option for option in selector.options if "D2" in option)
    selector.set_value(d2_label)
    app = app.run()
    app = next(button for button in app.button if button.label == "Open selected dispute →").click().run()
    assert app.session_state["unit_id"] == "d2u1"
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert "D2 first" in rendered
    assert '<div class="source-text">D2 later</div>' not in rendered


def test_completed_dispute_can_reopen_utterance_review(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    book = load_codebook(synthetic_project.codebook_path)
    save_submitted(storage, book, "u1", "D1")
    save_submitted(storage, book, "u2", "D1")
    storage.save_dispute(
        coder="coder_01",
        dispute_id="D1",
        payload={
            "C_primary_dispute_object": "wording_or_framing",
            "coder_confidence": 5,
            "review_flag": 0,
            "short_justification": None,
            "coder_notes": None,
        },
        answered_fields={"C_primary_dispute_object", "coder_confidence", "review_flag"},
        schema_version=schema_id(book.file_hash),
        schema_hash=book.file_hash,
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    app = configured_app(monkeypatch, synthetic_project)
    selector = next(select for select in app.selectbox if select.label == "Dispute")
    selector.set_value(selector.options[0])
    app = app.run()
    app = next(button for button in app.button if button.label == "Open dispute →").click().run()
    assert app.session_state["unit_id"] == "u1"
    assert any(button.label == "Review dispute decision →" for button in app.button)


def test_dispute_tasks_are_numbered_and_unsaved_navigation_requires_confirmation(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    book = load_codebook(synthetic_project.codebook_path)
    save_submitted(storage, book, "u1", "D1")
    save_submitted(storage, book, "u2", "D1")
    app = configured_app(monkeypatch, synthetic_project)
    app = next(button for button in app.button if button.label == "Complete dispute").click().run()
    assert task_titles(app) == [
        (1, "What is the primary dispute object?"),
        (2, "How confident are you in the dispute-level decision?"),
        (3, "Should this dispute-level decision be flagged for review?"),
        (4, "Add an optional note"),
    ]
    assert not any(radio.label == "C_primary_dispute_object" for radio in app.radio)
    next(radio for radio in app.radio if radio.label == "Primary dispute object").set_value("wording_or_framing")
    app = app.run()
    app = next(button for button in app.button if button.label == "← Workspace").click().run()
    assert app.title[0].value == "Complete dispute-level coding"
    assert any(button.label == "Discard changes and continue" for button in app.button)
    app = next(button for button in app.button if button.label == "Discard changes and continue").click().run()
    assert app.title[0].value == "Annotation workspace"
    assert not storage.rows("dispute_annotation_events", "coder_01")
