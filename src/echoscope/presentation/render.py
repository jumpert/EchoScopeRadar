import unicodedata

from rich.text import Text

from echoscope.domain.models import Observation, Severity

STYLES = {
    Severity.INFO: (1, "bold #f6cb69"),
    Severity.IMPORTANT: (2, "bold #ffab62"),
    Severity.CRITICAL: (3, "bold white on #9c253b"),
}
LABELS = {Severity.INFO: "INFO", Severity.IMPORTANT: "IMPORTANTE", Severity.CRITICAL: "CRÍTICA"}


def safe(value: str) -> str:
    # Keep exactly one code point per input code point, so match offsets stay valid.
    return "".join(
        character
        if character in "\n\t\u200c\u200d"
        or unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
        else "�"
        for character in value
    )


def line(value: str) -> str:
    return safe(value).replace("\n", " ").replace("\t", " ")


def highlighted(observation: Observation, *, single_line=False) -> Text:
    content = line(observation.message.text) if single_line else safe(observation.message.text)
    result = Text(content)
    for match in sorted(
        observation.matches,
        key=lambda item: (STYLES[item.severity][0], item.priority, item.end - item.start),
    ):
        result.stylize(STYLES[match.severity][1], match.start, match.end)
    return result


def preview(observation: Observation) -> Text:
    message = observation.message
    timestamp = (message.published_at or message.captured_at).astimezone()
    result = Text(no_wrap=True, overflow="ellipsis")
    result.append(f"{timestamp:%H:%M} {line(message.author or '—')[:24]}  ", style="dim")
    result.append_text(highlighted(observation, single_line=True))
    result.truncate(180, overflow="ellipsis")
    return result


def display(observation: Observation, *, details=False) -> Text:
    message = observation.message
    timestamp = (message.published_at or message.captured_at).astimezone()
    result = Text(
        f"{line(message.author or 'Autor sin identificar')} · {timestamp:%Y-%m-%d %H:%M:%S}",
        style="dim",
    )
    result.append("\n")
    result.append_text(highlighted(observation))
    if details and message.url:
        result.append(f"\n{line(message.url)}", style="cyan")
    return result
