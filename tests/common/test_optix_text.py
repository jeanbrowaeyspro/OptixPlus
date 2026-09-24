"""Lecture/écriture CRLF-safe : le contenu doit être préservé octet pour octet."""

import hashlib
from pathlib import Path

import pytest

from optixplus.common.optix.text import (
    TextFile,
    detect_eol,
    is_probably_text,
    read_text_file,
    split_lines,
    write_text_file,
)


@pytest.mark.parametrize(
    "raw",
    [
        b"a\r\nb\r\n",
        b"a\r\nb",
        b"a\nb\n",
        b"a\nb",
        b"",
        b"seul",
        b"\r\n",
        b"\r\n\r\n",
        b"\xef\xbb\xbfavec bom\r\nligne\r\n",
        b"vide au milieu\r\n\r\nfin\r\n",
    ],
)
def test_round_trip_is_identical(raw: bytes) -> None:
    assert split_lines(raw).to_bytes() == raw


@pytest.mark.parametrize(
    ("raw", "eol", "lines", "final_eol"),
    [
        (b"Name: A\r\n  Type: B\r\n", b"\r\n", [b"Name: A", b"  Type: B"], True),  # CRLF détecté
        (b"a\nb", b"\n", [b"a", b"b"], False),  # LF détecté
        (b"1.3.2.9-Stable", b"\r\n", [b"1.3.2.9-Stable"], False),  # sans saut de ligne : réputé CRLF
    ],
)
def test_line_ending_is_detected(raw: bytes, eol: bytes, lines: list[bytes], final_eol: bool) -> None:
    tf = split_lines(raw)
    assert detect_eol(raw) == tf.eol == eol
    assert tf.eol_name == ("CRLF" if eol == b"\r\n" else "LF")
    assert tf.lines == lines
    assert tf.final_eol is final_eol


def test_added_line_uses_the_file_line_ending() -> None:
    tf = split_lines(b"a\r\nb\r\n")
    tf.lines.insert(1, b"nouvelle")
    assert tf.to_bytes() == b"a\r\nnouvelle\r\nb\r\n"


def test_write_is_checked_by_reading_back(tmp_path: Path) -> None:
    target = tmp_path / "f.yaml"
    tf = TextFile(lines=[b"x", b"y"], eol=b"\r\n", final_eol=True)
    md5 = write_text_file(target, tf)
    assert target.read_bytes() == b"x\r\ny\r\n"
    assert md5 == hashlib.md5(b"x\r\ny\r\n").hexdigest()
    assert read_text_file(target).lines == [b"x", b"y"]


def test_text_heuristic() -> None:
    assert is_probably_text(b"\x00\x01", ".yaml") is True
    assert is_probably_text(b"MZ\x90\x00", ".dll") is False
    assert is_probably_text(b"texte simple", "") is True
    assert is_probably_text(b"", ".bin") is True
