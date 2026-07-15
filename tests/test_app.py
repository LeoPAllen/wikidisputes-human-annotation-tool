from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_coder_entry_and_first_focal(monkeypatch, synthetic_project):
    config = synthetic_project.root / "project.toml"
    config.write_text(
        f'''schema_version="0.9.7"\nschema_sheet="Core_Schema_SIMPLIFIED"\nphase="calibration"\nschema_locked=false\nlow_confidence_threshold=2\ngold_path="{synthetic_project.gold_path}"\ncodebook_path="{synthetic_project.codebook_path}"\ndatabase_path="{synthetic_project.database_path}"\nexport_directory="{synthetic_project.export_directory}"\n'''
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
    assert not any("Reply" in markdown.value or "Final" in markdown.value for markdown in app.markdown)
