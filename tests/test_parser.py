"""Tests for the email parser and quote stripping."""
import pytest
from src.extraction.parser import (
    strip_quotes,
    normalize_subject,
    detect_language,
    compute_delta_hash,
    parse_raw_email,
)


class TestStripQuotes:
    def test_french_attribution_line(self):
        text = "Bonjour,\n\nMerci pour ta réponse.\n\nLe 01/01/2024 à 14:30, Marie Dupont <marie@example.com> a écrit :\n> Voici mon message original."
        result = strip_quotes(text)
        assert "Merci pour ta réponse" in result
        assert "Voici mon message original" not in result

    def test_english_attribution_line(self):
        text = "Hello,\n\nThank you.\n\nOn Mon, Jan 1, 2024 at 2:30 PM, John Smith <john@example.com> wrote:\n> Original message here."
        result = strip_quotes(text)
        assert "Thank you" in result
        assert "Original message here" not in result

    def test_french_separator(self):
        text = "Nouvelle réponse.\n\n-----Message d'origine-----\nMessage précédent."
        result = strip_quotes(text)
        assert "Nouvelle réponse" in result
        assert "Message précédent" not in result

    def test_english_separator(self):
        text = "New reply.\n\n-----Original Message-----\nOld message."
        result = strip_quotes(text)
        assert "New reply" in result
        assert "Old message" not in result

    def test_angle_bracket_quotes(self):
        text = "My reply.\n> This is quoted.\n> More quoted."
        result = strip_quotes(text)
        assert "My reply" in result
        assert "This is quoted" not in result

    def test_no_quotes(self):
        text = "Simple message with no quotes at all."
        result = strip_quotes(text)
        assert result == text

    def test_empty_input(self):
        assert strip_quotes("") == ""


class TestNormalizeSubject:
    def test_re_prefix(self):
        assert normalize_subject("Re: Hello") == "Hello"
        assert normalize_subject("RE: Hello") == "Hello"

    def test_tr_prefix(self):
        assert normalize_subject("TR: Bonjour") == "Bonjour"
        assert normalize_subject("Tr: Bonjour") == "Bonjour"

    def test_fwd_prefix(self):
        assert normalize_subject("Fwd: Hello") == "Hello"
        assert normalize_subject("Fw: Hello") == "Hello"

    def test_multiple_prefixes(self):
        assert normalize_subject("Re: Re: TR: Hello") == "Hello"

    def test_no_prefix(self):
        assert normalize_subject("Important matter") == "Important matter"


class TestDetectLanguage:
    def test_french_text(self):
        text = "Bonjour, je voudrais vous informer que nous avons un problème avec le logement."
        assert detect_language(text) == "fr"

    def test_english_text(self):
        text = "Hello, I would like to inform you that we have a problem with the apartment."
        assert detect_language(text) == "en"

    def test_empty_text(self):
        assert detect_language("") == "unknown"


class TestDeltaHash:
    def test_same_content_same_hash(self):
        assert compute_delta_hash("Hello world") == compute_delta_hash("Hello world")

    def test_whitespace_normalized(self):
        # Extra whitespace shouldn't change hash
        assert compute_delta_hash("Hello  world") == compute_delta_hash("Hello world")

    def test_case_normalized(self):
        assert compute_delta_hash("Hello World") == compute_delta_hash("hello world")

    def test_different_content(self):
        assert compute_delta_hash("Hello") != compute_delta_hash("Goodbye")
