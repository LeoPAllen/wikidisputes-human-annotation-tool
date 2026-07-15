import pandas as pd

from wikidisputes_ui.ui_components import safe_source_text


def test_safe_source_text_escapes_and_preserves_whitespace():
    source = "First line\n*not wiki* <script>alert('x')</script>"
    rendered = safe_source_text(source)
    assert "\n" in rendered
    assert "*not wiki*" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert safe_source_text(pd.NA) == ""
