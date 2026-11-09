import hashlib
import unicodedata
from dataclasses import dataclass

import regex

from .models import Match, Severity

GRAPHEMES = regex.compile(r"\X")
WORD = regex.compile(r"[\p{L}\p{M}\p{N}_]")


def _normalized(text: str, case_sensitive: bool, accent_sensitive: bool) -> str:
    text = unicodedata.normalize("NFD", text if case_sensitive else text.casefold())
    if not accent_sensitive:
        text = "".join(character for character in text if not unicodedata.combining(character))
    return unicodedata.normalize("NFC", text)


def _ranges(text: str, phrase: str):
    if not phrase:
        return
    offset = 0
    while (start := text.find(phrase, offset)) != -1:
        end = start + len(phrase)
        offset = start + 1
        if start and WORD.fullmatch(phrase[0]) and WORD.fullmatch(text[start - 1]):
            continue
        if end < len(text) and WORD.fullmatch(phrase[-1]) and WORD.fullmatch(text[end]):
            continue
        yield start, end


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    phrase: str
    severity: Severity = Severity.INFO
    priority: int = 0
    case_sensitive: bool = False
    accent_sensitive: bool = False
    exclusions: tuple[str, ...] = ()

    @property
    def revision(self) -> str:
        return hashlib.sha256(repr(self).encode()).hexdigest()


def evaluate(text: str, rules: tuple[Rule, ...]) -> tuple[Match, ...]:
    projections = {}
    matches = []
    for rule in rules:
        options = rule.case_sensitive, rule.accent_sensitive
        if options not in projections:
            parts, spans = [], []
            for grapheme in GRAPHEMES.finditer(text):
                part = _normalized(grapheme.group(), *options)
                parts.append(part)
                spans.extend([grapheme.span()] * len(part))
            projections[options] = "".join(parts), spans
        projected, spans = projections[options]
        exclusions = [
            span
            for phrase in rule.exclusions
            for span in _ranges(projected, _normalized(phrase, *options))
        ]
        for start, end in _ranges(projected, _normalized(rule.phrase, *options)):
            if any(left < end and start < right for left, right in exclusions):
                continue
            left, right = spans[start][0], spans[end - 1][1]
            matches.append(
                Match(
                    left,
                    right,
                    text[left:right],
                    rule.id,
                    rule.revision,
                    rule.severity,
                    rule.priority,
                )
            )
    return tuple(sorted(set(matches), key=lambda item: (item.start, item.end, item.rule_id)))
