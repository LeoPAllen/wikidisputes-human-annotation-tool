from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_coder_entry_and_first_focal(monkeypatch, synthetic_project):
    config = synthetic_project.root / "project.toml"
    config.write_text(
        f'''schema_version="0.9.7"\nschema_sheet="Core_Schema_SIMPLIFIED"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\nlow_confidence_threshold=2\ngold_path="{synthetic_project.gold_path}"\ncodebook_path="{synthetic_project.codebook_path}"\ndatabase_path="{synthetic_project.database_path}"\nexport_directory="{synthetic_project.export_directory}"\n'''
    )
    monkeypatch.setenv("WIKIDISPUTES_CONFIG", str(config))
    app = AppTest.from_file(str(Path("app.py").resolve()), default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "WikiDisputes annotation"
    app.text_input[0].input("coder_01")
    next(button for button in app.button if button.label == "Continue").click().run()
    assert not app.exception
    next(button for button in app.button if button.label == "Resume annotation").click().run()
    assert not app.exception
    assert any("First proposal" in markdown.value for markdown in app.markdown)
    assert any("Conversation heading" in markdown.value for markdown in app.markdown)
    assert not any(">Reply<" in markdown.value for markdown in app.markdown)
    forbidden = ("escalated", "dispute_resolution_url", "Dispute_Rationales", "Validation_Audit")
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert not any(name in rendered for name in forbidden)

    def submit_negative_turn(test_app):
        selections = {
            "KS_present": 0,
            "KI_present": 0,
            "C_interpersonal_hostility": 0,
            "C_formal_escalation_signal": 0,
            "coder_confidence": 5,
            "review_flag": 0,
        }
        for label, value in selections.items():
            next(radio for radio in test_app.radio if radio.label == label).set_value(value)
        return next(button for button in test_app.button if button.label == "Submit and next").click().run()

    app = submit_negative_turn(app)
    assert any("Reply" in markdown.value for markdown in app.markdown)
    utterance_timer = app.session_state["utterance_timer_start"]
    app = submit_negative_turn(app)
    assert app.title[0].value == "Complete dispute-level coding"
    assert app.session_state["dispute_timer_start"] > utterance_timer
    assert "dispute_opened_at" in app.session_state and "utterance_opened_at" in app.session_state
