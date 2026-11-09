from echoscope.domain.models import Kind, Message, Observation, Severity
from echoscope.domain.rules import Rule, evaluate
from echoscope.presentation.render import highlighted


def test_unicode_exact_offsets_and_overlaps():
    text = "👩🏽‍💻 ¡ATENCIÓN al cliente! atención y atencional."
    matches = evaluate(text, (Rule("word", "atención"), Rule("phrase", "atención al cliente")))
    assert [text[match.start : match.end] for match in matches] == [
        "ATENCIÓN",
        "ATENCIÓN al cliente",
        "atención",
    ]
    assert (
        len(
            evaluate(
                text, (Rule("strict", "atención", case_sensitive=True, accent_sensitive=True),)
            )
        )
        == 1
    )
    assert not evaluate("sin demora", (Rule("delay", "demora", exclusions=("sin demora",)),))
    assert len(evaluate("Straße", (Rule("fold", "STRASSE"),))) == 1


def test_terminal_projection_preserves_offsets():
    text = "\x1b[31m [bold] demora \u202e"
    message = Message(Kind.COMMENT, "test", "1", "1", text)
    view = highlighted(
        Observation(message, evaluate(text, (Rule("x", "demora", Severity.CRITICAL),)))
    )
    assert "\x1b" not in view.plain and "\u202e" not in view.plain
    assert "[bold]" in view.plain
    assert view.plain[view.spans[0].start : view.spans[0].end] == "demora"
