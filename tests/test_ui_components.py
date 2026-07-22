import pandas as pd

from wikidisputes_ui.codebook import FieldGuide
import wikidisputes_ui.ui_components as components
from wikidisputes_ui.ui_components import TaskCounter, binary_guidance_text, safe_source_text


def test_safe_source_text_escapes_and_preserves_whitespace():
    source = "First line\n*not wiki* <script>alert('x')</script>"
    rendered = safe_source_text(source)
    assert "\n" in rendered
    assert "*not wiki*" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert safe_source_text(pd.NA) == ""


def test_binary_guidance_uses_labels_presented_by_the_control():
    guidance = "If KS_present=1, code 1; otherwise code 0. If KS_present=0, return null."

    assert binary_guidance_text(guidance) == (
        "If KS_present=Yes, code Yes; otherwise code No. If KS_present=No, return null."
    )


def test_binary_guidance_does_not_change_digits_within_larger_numbers():
    assert binary_guidance_text("Use schema 10 and retain 2021.") == "Use schema 10 and retain 2021."


def test_binary_task_renders_heading_guidance_then_answer(monkeypatch):
    calls = []

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeStreamlit:
        def markdown(self, value, **kwargs):
            calls.append(("markdown", value))

        def container(self, **kwargs):
            calls.append(("container", kwargs))
            return Context()

        def caption(self, value):
            calls.append(("definition", value))

        def expander(self, label):
            calls.append(("guidance", label))
            return Context()

        def write(self, value):
            calls.append(("rule", value))

        def radio(self, label, options, **kwargs):
            calls.append(("answer", label))
            return None

    monkeypatch.setattr(components, "st", FakeStreamlit())
    item = FieldGuide("KS", "KS_present", "binary {0,1}", "Definition", "Code 1; otherwise 0.", "Example")
    counter = TaskCounter()
    components.binary_task(counter, "Knowledge staking", item, "ks")
    kinds = [kind for kind, _ in calls]
    assert kinds.index("markdown") < kinds.index("definition") < kinds.index("guidance") < kinds.index("answer")
    assert counter.value == 1
