import hashlib
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import regex

from .models import Match, Severity

GRAPHEMES = regex.compile(r"\X")
WORD = regex.compile(r"[\p{L}\p{M}\p{N}_]")
TOKEN = regex.compile(r"[\p{L}\p{M}\p{N}_]+")
LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}


@lru_cache(maxsize=512)
def _disguised(term: str):
    def character(letter):
        digits = "".join(digit for digit, value in LEET.items() if value == letter.lower())
        return f"[{regex.escape(letter)}{digits}]" if digits else regex.escape(letter)

    words = term.split()
    if not words or any(not word.isalpha() for word in words):
        return None
    groups = [
        r"[ .·_\u200b\u200c\u200d-]{0,2}".join(map(character, word))
        if len(word) >= 4
        else "".join(map(character, word))
        for word in words
    ]
    return regex.compile(
        r"(?<![\p{L}\p{M}\p{N}_])" + r"\s+".join(groups) + r"(?![\p{L}\p{M}\p{N}_])"
    )


@lru_cache(maxsize=512)
def _approximate(term: str):
    return regex.compile(f"(?:{regex.escape(term)}){{e<=1}}")


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
    aliases: tuple[str, ...] = field(default=(), repr=False)
    detect_variants: bool = field(default=False, repr=False)

    @property
    def revision(self) -> str:
        variants = (
            repr((self.aliases, self.detect_variants))
            if self.aliases or self.detect_variants
            else ""
        )
        return hashlib.sha256((repr(self) + variants).encode()).hexdigest()


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
        term = _normalized(rule.phrase, *options)
        found = {span: "exact" for span in _ranges(projected, term)}
        for alias in rule.aliases:
            for span in _ranges(projected, _normalized(alias, *options)):
                found.setdefault(span, "approved")
        if rule.detect_variants:
            for variant in (term, *(_normalized(alias, *options) for alias in rule.aliases)):
                if pattern := _disguised(variant):
                    for hit in pattern.finditer(projected):
                        if any(character.isalpha() for character in hit.group()):
                            found.setdefault(hit.span(), "disguised")
            if term.isalpha() and 6 <= len(term) <= 30:
                count = 0
                for token in TOKEN.finditer(projected):
                    word = token.group()
                    if abs(len(word) - len(term)) > 1 or word[0] != term[0] or not word.isalpha():
                        continue
                    if token.span() not in found and _approximate(term).fullmatch(word):
                        found[token.span()] = "review"
                        count += 1
                        if count >= 20:
                            break
        confirmed = [span for span, method in found.items() if method != "review"]
        for (start, end), method in found.items():
            if any(left < end and start < right for left, right in exclusions):
                continue
            if method == "review" and any(
                left < end and start < right for left, right in confirmed
            ):
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
                    method,
                    rule.phrase if method != "exact" else None,
                )
            )
    return tuple(sorted(set(matches), key=lambda item: (item.start, item.end, item.rule_id)))
