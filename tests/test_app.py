import json

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


def answer_all(app, ks=0, ki=0):
    radio(app, "Does this utterance state or challenge substantive knowledge about the article or dispute?").set_value(
        ks
    )
    app = app.run()
    if ks:
        for label in (
            "Does it make a substantive claim?",
            "Does it directly refer to evidence or another supporting basis?",
            "Does it connect evidence or a premise to a conclusion?",
            "Does it repeat an earlier claim or objection without adding evidence or reasoning?",
        ):
            radio(app, label).set_value(0)
    radio(app, "Does this utterance propose, report, or refine an article edit?").set_value(ki)
    app = app.run()
    if ki:
        radio(app, "Does it ask others to assess, revise, or accept that edit?").set_value(0)
        radio(app, "Does the edit visibly accommodate at least two positions or concerns?").set_value(0)
    for label in (
        "Does this shift away from the article dispute?",
        "Does this attack or disrespect another contributor?",
        "Does this invoke or threaten a formal governance action?",
    ):
        radio(app, label).set_value(0)
    radio(app, "How confident are you in this utterance annotation?").set_value(3)
    radio(app, "Flag this utterance for review?").set_value(0)
    return app


def test_inline_workflow_has_no_stages_and_conditional_children(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    labels = {item.label for item in app.radio}
    assert "Does it make a substantive claim?" not in labels
    radio(app, "Does this utterance state or challenge substantive knowledge about the article or dispute?").set_value(
        1
    )
    radio(app, "Does this utterance propose, report, or refine an article edit?").set_value(1)
    app = app.run()
    labels = {item.label for item in app.radio}
    assert len(set(KS_CHILD_LABELS) & labels) == 4
    assert len(set(KI_CHILD_LABELS) & labels) == 2
    rendered = " ".join(str(m.value) for m in app.markdown)
    assert "Stage 1" not in rendered and "Stage 2" not in rendered and "Continue to details" not in rendered
    assert len([item for item in app.text_area if item.label == "Optional comment"]) == 1


KS_CHILD_LABELS = (
    "Does it make a substantive claim?",
    "Does it directly refer to evidence or another supporting basis?",
    "Does it connect evidence or a premise to a conclusion?",
    "Does it repeat an earlier claim or objection without adding evidence or reasoning?",
)
KI_CHILD_LABELS = (
    "Does it ask others to assess, revise, or accept that edit?",
    "Does the edit visibly accommodate at least two positions or concerns?",
)


def test_parent_change_hides_and_clears_children(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    radio(app, "Does this utterance state or challenge substantive knowledge about the article or dispute?").set_value(
        1
    )
    app = app.run()
    radio(app, KS_CHILD_LABELS[3]).set_value(1)
    radio(app, "Does this utterance state or challenge substantive knowledge about the article or dispute?").set_value(
        0
    )
    app = app.run()
    assert not set(KS_CHILD_LABELS) & {item.label for item in app.radio}


def test_full_dispute_smoke_and_object_only_payload(monkeypatch, synthetic_project):
    app = enter(configured(monkeypatch, synthetic_project))
    app = answer_all(app)
    app = next(b for b in app.button if b.label == "Submit and next").click().run()
    assert app.session_state["unit_id"] == "u2"
    app = answer_all(app, ks=1, ki=1)
    app = next(b for b in app.button if b.label == "Submit and next").click().run()
    assert app.title[0].value == "Final dispute decision"
    assert [item.label for item in app.radio] == ["C_primary_dispute_object"]
    app.radio[0].set_value("wording_or_framing")
    app = next(b for b in app.button if b.label == "Complete dispute").click().run()
    row = Storage(synthetic_project.database_path).rows("dispute_annotations", "coder_01")[0]
    assert json.loads(row["payload_json"]) == {"C_primary_dispute_object": "wording_or_framing"}
    assert json.loads(
        Storage(synthetic_project.database_path).rows("dispute_annotation_events", "coder_01")[0][
            "answered_fields_json"
        ]
    ) == ["C_primary_dispute_object"]


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


def test_dispute_object_blocked_before_all_submissions(monkeypatch, synthetic_project):
    storage = Storage(synthetic_project.database_path)
    storage.set_active_coder("coder_01")
    app = configured(monkeypatch, synthetic_project)
    app.session_state["page"] = "dispute"
    app.session_state["dispute_id"] = "D1"
    app = app.run()
    assert not any(item.label == "C_primary_dispute_object" for item in app.radio)
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
