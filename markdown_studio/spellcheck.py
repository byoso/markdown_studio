"""Spell-check text while preserving source offsets for GtkTextIter."""
from __future__ import annotations

import re
import unicodedata

from spellchecker import SpellChecker


_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ]+(?:['’][\wÀ-ÖØ-öø-ÿ]+)?", re.UNICODE)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_FENCE_RE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_FRENCH_ELISION_PREFIXES = {
    "c",
    "d",
    "j",
    "l",
    "m",
    "n",
    "qu",
    "s",
    "t",
}


class SpellCheckerEngine:
    """Find misspelled words in a text using one or more dictionaries."""

    def __init__(self):
        self._checkers = {
            "en": SpellChecker(language="en"),
            "fr": SpellChecker(language="fr"),
        }
        self._accent_folded_words = {
            language: {self._fold_accents(word) for word in checker.word_frequency.dictionary}
            for language, checker in self._checkers.items()
        }

    def misspelled_spans(self, text: str, languages: list[str]) -> list[tuple[int, int]]:
        checker_languages = [
            (self._checkers[language], language)
            for language in languages
            if language in self._checkers
        ]
        checkers = [checker for checker, _language in checker_languages]
        if not checkers:
            return []

        ignored_ranges = self._ignored_ranges(text)
        spans = []
        for match in _WORD_RE.finditer(text):
            for start, end, word in self._spellcheck_parts(match):
                if self._is_ignored(start, end, word, ignored_ranges):
                    continue
                if all(not self._is_known(word, checker, language) for checker, language in checker_languages):
                    spans.append((start, end))
        return spans

    def _is_known(self, word: str, checker: SpellChecker, language: str) -> bool:
        normalized = word.replace("’", "'").lower()
        return normalized in checker or self._fold_accents(normalized) in self._accent_folded_words[language]

    @staticmethod
    def _spellcheck_parts(match: re.Match) -> list[tuple[int, int, str]]:
        start, end = match.span()
        word = match.group(0)
        apostrophe = re.search(r"['’]", word)
        if apostrophe is None:
            return [(start, end, word)]
        prefix = word[:apostrophe.start()].lower()
        if prefix not in _FRENCH_ELISION_PREFIXES:
            return [(start, end, word)]
        suffix_start = start + apostrophe.end()
        return [(suffix_start, end, word[apostrophe.end():])]

    @staticmethod
    def _fold_accents(word: str) -> str:
        decomposed = unicodedata.normalize("NFKD", word)
        return "".join(character for character in decomposed if not unicodedata.combining(character))

    def suggestions(self, word: str, languages: list[str], limit: int = 5) -> list[str]:
        suggestions = set()
        for language in languages:
            checker = self._checkers.get(language)
            if checker is not None:
                suggestions.update(checker.candidates(word) or ())
        return sorted(suggestions, key=lambda candidate: (abs(len(candidate) - len(word)), candidate))[:limit]

    @staticmethod
    def _ignored_ranges(text: str) -> list[tuple[int, int]]:
        ranges = [match.span() for pattern in (_URL_RE, _FENCE_RE, _HTML_TAG_RE) for match in pattern.finditer(text)]
        return sorted(ranges)

    @staticmethod
    def _is_ignored(start: int, end: int, word: str, ignored_ranges: list[tuple[int, int]]) -> bool:
        if any(start < range_end and end > range_start for range_start, range_end in ignored_ranges):
            return True
        return len(word) < 2 or any(character.isdigit() for character in word)