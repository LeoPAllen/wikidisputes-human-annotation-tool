from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest
import pytest


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
    assert not any(label in {radio.label for radio in app.radio} for label in ("Coder confidence", "Flag for review"))
    assert not app.text_area

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


def test_conditional_review_and_submission_navigation(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app)
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    confidence = next(radio for radio in app.radio if radio.label == "Coder confidence")
    review = next(radio for radio in app.radio if radio.label == "Flag for review")
    confidence.set_value(5)
    review.set_value(0)
    app = app.run()
    justification = next(area for area in app.text_area if area.label == "Short justification")
    assert not justification.disabled
    next(radio for radio in app.radio if radio.label == "Coder confidence").set_value(2)
    app = app.run()
    justification = next(area for area in app.text_area if area.label == "Short justification")
    assert not justification.disabled
    assert any("Required because confidence is low" in caption.value for caption in app.caption)
    app = next(button for button in app.button if button.label == "Submit and next").click().run()
    assert any("short_justification" in error.value for error in app.error)
    next(area for area in app.text_area if area.label == "Short justification").input("Needs review")
    app = next(button for button in app.button if button.label == "Submit and next").click().run()
    assert {radio.label for radio in app.radio} == GATEWAYS
    assert app.session_state["annotation_stage"] == 1


def test_coder_notes_explain_when_they_are_recorded(monkeypatch, synthetic_project):
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    app = set_gateways(app)
    app = next(button for button in app.button if button.label == "Continue to details").click().run()
    app = enter_first_utterance(configured_app(monkeypatch, synthetic_project))

    assert any("Notes are recorded when you save a draft or submit" in caption.value for caption in app.caption)
    next(area for area in app.text_area if area.label == "Coder notes").input("Check context")
    app = app.run()
    assert any("Coder notes entered" in caption.value for caption in app.caption)
    app = next(button for button in app.button if button.label == "Save draft").click().run()
    assert any("Draft saved" in success.value for success in app.success)

    reloaded = enter_first_utterance(configured_app(monkeypatch, synthetic_project))
    notes = next(area for area in reloaded.text_area if area.label == "Coder notes")
    assert notes.value == "Check context"


@pytest.mark.parametrize(
    ("positives", "present", "absent"),
    [
        (
            {"Knowledge staking (KS)": 1},
            {"Shares supporting evidence", "KS evidence span"},
            {"Proposes an edit", "KI evidence span", "Control evidence span"},
        ),
        (
            {"Knowledge integration (KI)": 1},
            {"Proposes an edit", "Solicits candidate feedback", "KI evidence span"},
            {"Shares supporting evidence", "KS evidence span", "Control evidence span"},
        ),
        (
            {"Interpersonal attack or disrespect": 1},
            {"Control evidence span"},
            {"Shares supporting evidence", "KS evidence span", "Proposes an edit", "KI evidence span"},
        ),
        (
            {"Knowledge staking (KS)": 1, "Knowledge integration (KI)": 1, "Formal governance action": 1},
            {
                "Shares supporting evidence",
                "KS evidence span",
                "Proposes an edit",
                "Solicits candidate feedback",
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
    assert "Explicit feedback on an earlier candidate" not in labels
