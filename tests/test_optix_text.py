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
def test_aller_retour_identique(raw: bytes) -> None:
    assert split_lines(raw).to_bytes() == raw


def test_crlf_detecte_et_conserve() -> None:
    tf = split_lines(b"Name: A\r\n  Type: B\r\n")
    assert tf.eol == b"\r\n"
    assert tf.eol_name == "CRLF"
    assert tf.lines == [b"Name: A", b"  Type: B"]
    assert tf.final_eol is True


def test_lf_detecte() -> None:
    tf = split_lines(b"a\nb")
    assert tf.eol == b"\n"
    assert tf.final_eol is False
    assert tf.lines == [b"a", b"b"]


def test_sans_saut_de_ligne_repute_crlf() -> None:
    assert detect_eol(b"1.3.2.9-Stable") == b"\r\n"
    tf = split_lines(b"1.3.2.9-Stable")
    assert tf.lines == [b"1.3.2.9-Stable"]
    assert tf.final_eol is False


def test_ajout_de_ligne_respecte_le_separateur() -> None:
    tf = split_lines(b"a\r\nb\r\n")
    tf.lines.insert(1, b"nouvelle")
    assert tf.to_bytes() == b"a\r\nnouvelle\r\nb\r\n"


def test_ecriture_verifie_par_relecture(tmp_path: Path) -> None:
    target = tmp_path / "f.yaml"
    tf = TextFile(lines=[b"x", b"y"], eol=b"\r\n", final_eol=True)
    md5 = write_text_file(target, tf)
    assert target.read_bytes() == b"x\r\ny\r\n"
    assert md5 == hashlib.md5(b"x\r\ny\r\n").hexdigest()
    assert read_text_file(target).lines == [b"x", b"y"]


def test_heuristique_texte() -> None:
    assert is_probably_text(b"\x00\x01", ".yaml") is True
    assert is_probably_text(b"MZ\x90\x00", ".dll") is False
    assert is_probably_text(b"texte simple", "") is True
    assert is_probably_text(b"", ".bin") is True
