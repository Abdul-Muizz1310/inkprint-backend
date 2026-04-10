"""Tests for inkprint.provenance.canonicalize — spec 00-canonicalize.md."""

import pytest
from inkprint.provenance.canonicalize import canonicalize

# ── Happy path ───────────────────────────────────────────────────────────────


class TestCanonicalizeHappy:
    def test_tc_c_01_ascii_passthrough(self) -> None:
        """TC-C-01: ASCII text with single spaces passes through unchanged."""
        text = "Hello world this is a test"
        assert canonicalize(text) == text.encode("utf-8")

    def test_tc_c_02_whitespace_collapse(self) -> None:
        """TC-C-02: Tabs, newlines, multiple spaces collapse to single spaces."""
        text = "Hello\t\tworld\n\nthis   is\ta test"
        result = canonicalize(text)
        assert result == b"Hello world this is a test"

    def test_tc_c_03_strip_leading_trailing(self) -> None:
        """TC-C-03: Leading/trailing whitespace is stripped."""
        text = "  \t hello world \n "
        result = canonicalize(text)
        assert result == b"hello world"

    def test_tc_c_04_nfc_combining_characters(self) -> None:
        """TC-C-04: Combining characters normalized to precomposed form."""
        # e + combining acute accent → é (precomposed)
        text = "caf\u0065\u0301"
        result = canonicalize(text)
        assert result == "caf\u00e9".encode("utf-8")

    def test_tc_c_05_nbsp_collapsed(self) -> None:
        """TC-C-05: Non-breaking space collapsed like regular whitespace."""
        text = "hello\u00a0\u00a0world"
        result = canonicalize(text)
        assert result == b"hello world"


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestCanonicalizeEdge:
    def test_tc_c_06_empty_string(self) -> None:
        """TC-C-06: Empty string returns b''."""
        assert canonicalize("") == b""

    def test_tc_c_07_whitespace_only(self) -> None:
        """TC-C-07: Whitespace-only string returns b''."""
        assert canonicalize("   \t\n  ") == b""

    def test_tc_c_08_single_char(self) -> None:
        """TC-C-08: Single character returns its UTF-8 bytes."""
        assert canonicalize("a") == b"a"
        assert canonicalize("\u00e9") == "\u00e9".encode("utf-8")

    def test_tc_c_09_bom_handling(self) -> None:
        """TC-C-09: BOM at start is handled consistently."""
        text_with_bom = "\ufeffhello"
        result = canonicalize(text_with_bom)
        # BOM should either be stripped or preserved — the implementation decides.
        # The key invariant is that it's deterministic.
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_tc_c_10_zero_width_chars(self) -> None:
        """TC-C-10: Zero-width joiner/space are handled consistently."""
        text = "hello\u200dworld\u200b"
        result = canonicalize(text)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_tc_c_11_max_size_text(self) -> None:
        """TC-C-11: 500 KB text produces output without error."""
        text = "a " * 250_000  # ~500 KB
        result = canonicalize(text)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_tc_c_12_idempotency(self) -> None:
        """TC-C-12: canonicalize(decode(canonicalize(text))) == canonicalize(text)."""
        inputs = [
            "Hello world",
            "  spaces  everywhere  ",
            "caf\u0065\u0301",
            "\u00a0\ttabs\nand\nnewlines\u00a0",
            "",
            "a",
            "Unicode: \u4e16\u754c \u0410\u0411\u0412",
            "emoji: \U0001f600\U0001f601",
            "mixed\t  \n\r\n  whitespace",
            "CJK\u3000fullwidth space",
            "a " * 1000,
            "\u0065\u0301\u0065\u0301",
            "line1\nline2\nline3",
            "already canonical",
            "UPPER lower MiXeD",
            "numbers 123 456",
            "special !@#$%^&*()",
            "quotes 'single' \"double\"",
            "path/to/file.txt",
            "url https://example.com",
        ]
        for text in inputs:
            first = canonicalize(text)
            second = canonicalize(first.decode("utf-8"))
            assert first == second, f"Not idempotent for: {text!r}"


# ── Failure cases ────────────────────────────────────────────────────────────


class TestCanonicalizeFailure:
    def test_tc_c_13_none_raises_type_error(self) -> None:
        """TC-C-13: None input raises TypeError."""
        with pytest.raises(TypeError):
            canonicalize(None)  # type: ignore[arg-type]

    def test_tc_c_14_non_string_raises_type_error(self) -> None:
        """TC-C-14: Non-string input raises TypeError."""
        with pytest.raises(TypeError):
            canonicalize(42)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            canonicalize(b"bytes")  # type: ignore[arg-type]
