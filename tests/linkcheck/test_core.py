"""Link Checker : lecture du projet, résolution, suggestions, corrections en tout ou rien."""

from __future__ import annotations

import os

import pytest

from linkcheck_fixture import make_project
from optixplus.common.progress import Cancelled
from optixplus.modules.linkcheck.core import fixer
from optixplus.modules.linkcheck.core.project import (
    REASON_ABOVE_ROOT,
    REASON_FOREIGN,
    REASON_MISSING,
    OptixProject,
    ProjectError,
    analyse,
    read_project_meta,
)


@pytest.fixture
def demo(tmp_path):
    return make_project(tmp_path)


def _by_prop_owner(broken):
    return {b.owner_path.split("/")[-2]: b for b in broken}


def test_project_meta_is_read_from_project_block(demo):
    assert read_project_meta(str(demo)) == ("Demo", "Nodes/Demo.yaml")


def test_not_a_project(tmp_path):
    with pytest.raises(ProjectError):
        OptixProject(str(tmp_path))


def test_optix_file_path_is_accepted(demo):
    project = OptixProject(str(demo / "Demo.optix"))
    assert project.folder == str(demo)


def test_broken_links_and_stats(demo):
    project, broken, stats = analyse(str(demo))
    assert project.name == "Demo"
    assert project.files_loaded == 3
    found = _by_prop_owner(broken)
    assert set(found) == {"LabelForeign", "LabelMissing", "LabelAbove", "LabelForeignBare", "LabelForeignMissing"}
    assert found["LabelForeign"].reason == REASON_FOREIGN and found["LabelForeign"].detail == "OldProject"
    assert found["LabelMissing"].reason == REASON_MISSING and found["LabelMissing"].detail == "Old"
    assert found["LabelAbove"].reason == REASON_ABOVE_ROOT
    assert found["LabelForeign"].screen == "UI/Screens/Main"
    assert (stats.resolved, stats.alias, stats.pointer, stats.builtin) == (4, 1, 1, 1)


def test_suggestions_keep_the_form_of_the_link(demo):
    _project, broken, _stats = analyse(str(demo))
    found = _by_prop_owner(broken)
    assert found["LabelForeign"].suggestions[0] == "/Objects/Demo/Model/Speed"
    assert found["LabelMissing"].suggestions[0] == "../../../../../Model/Speed"


def test_progress_counts_only_included_files(demo):
    (demo / "Nodes" / "Orphan.yaml").write_text("Name: Orphan\nType: FolderType\n", encoding="utf-8")
    steps = []
    analyse(str(demo), progress=steps.append)
    loading = [s for s in steps if s.current]
    assert loading[-1].index == loading[-1].total == 3


def test_analysis_can_be_cancelled(demo):
    with pytest.raises(Cancelled):
        analyse(str(demo), cancel=lambda: True)


def test_deep_tree_does_not_hit_recursion_limit(tmp_path):
    folder = make_project(tmp_path)
    depth = 1200  # au-delà de la limite de récursion de Python (1000), qui faisait planter l'outil d'origine
    lines = ["Name: Model", "Type: FolderType", "Children:"]
    for i in range(depth):
        pad = "  " * i
        lines += [f"{pad}- Name: N{i}", f"{pad}  Type: FolderType", f"{pad}  Children:"]
    lines.append("  " * depth + "- Name: Leaf")
    (folder / "Nodes" / "Model" / "Model.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    project = OptixProject(str(folder)).load()
    assert len(project.all_nodes) > depth


# ---- corrections --------------------------------------------------------------------
def test_prefix_fixes_skip_targets_absent_from_project(demo):
    project, broken, _ = analyse(str(demo))
    fixes, skipped = fixer.propose_prefix_fixes(project, broken)
    assert sorted(f.link.owner_path.split("/")[-2] for f in fixes) == ["LabelForeign", "LabelForeignBare"]
    assert [s[0].owner_path.split("/")[-2] for s in skipped] == ["LabelForeignMissing"]


def test_fixes_preserve_crlf_bom_and_quotes(demo, tmp_path):
    project, broken, _ = analyse(str(demo))
    fixes, _ = fixer.propose_prefix_fixes(project, broken)
    result = fixer.apply_fixes(project, fixes, backup_dir=str(tmp_path / "backup"))
    assert result.files == 1
    raw = (demo / "Nodes" / "UI" / "UI.yaml").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")  # aucune fin de ligne LF isolée
    text = raw.decode("utf-8-sig")
    assert 'Value: "/Objects/Demo/Model/Speed"' in text  # guillemets conservés
    assert "Value: /Objects/Demo/Model/Speed\r\n" in text  # valeur nue conservée nue
    assert "OldProject/Model/Speed" not in text
    assert (tmp_path / "backup" / "Nodes" / "UI" / "UI.yaml").read_bytes() != raw
    _project, after, _ = analyse(str(demo))
    assert "LabelForeign" not in _by_prop_owner(after)


def test_remove_deletes_only_the_link_block(demo, tmp_path):
    project, broken, _ = analyse(str(demo))
    above = _by_prop_owner(broken)["LabelAbove"]
    fixer.apply_fixes(project, [fixer.Fix(above, fixer.ACTION_REMOVE)], backup_dir=str(tmp_path / "bk"))
    project2, after, stats = analyse(str(demo))
    assert "LabelAbove" not in _by_prop_owner(after)
    assert len(after) == len(broken) - 1
    assert stats.resolved == 4
    assert "LabelAbove" in (demo / "Nodes" / "UI" / "UI.yaml").read_text(encoding="utf-8-sig")


def test_stale_analysis_modifies_nothing(demo, tmp_path):
    """Si un fichier a changé depuis l'analyse, aucune correction n'est écrite (tout ou rien)."""
    project, broken, _ = analyse(str(demo))
    fixes, _ = fixer.propose_prefix_fixes(project, broken)
    ui = demo / "Nodes" / "UI" / "UI.yaml"
    raw = ui.read_bytes().replace(b"/Objects/OldProject/Model/Speed\r\n", b"/Objects/Changed/Speed\r\n")
    ui.write_bytes(raw)
    with pytest.raises(fixer.FixError):
        fixer.apply_fixes(project, fixes, backup_dir=str(tmp_path / "bk"))
    assert ui.read_bytes() == raw
    assert not (tmp_path / "bk").exists()


def test_write_failure_restores_every_file(demo, tmp_path, monkeypatch):
    """Échec au 2e fichier : le 1er, déjà écrit, est restauré depuis la sauvegarde."""
    project, broken, _ = analyse(str(demo))
    model = demo / "Nodes" / "Model" / "Model.yaml"
    ui = demo / "Nodes" / "UI" / "UI.yaml"
    before = {p: p.read_bytes() for p in (model, ui)}
    # Un lien fictif dans Model.yaml, pour avoir deux fichiers à écrire.
    speed_line = before[model].decode().splitlines().index('  Value: "/Objects/Demo/Model/Speed"') + 1
    fake = fixer.BrokenLink(str(model), speed_line, 0, 0, "", "", "/Objects/Demo/Model/Speed", "", "", "")
    fixes = [fixer.Fix(fake, fixer.ACTION_REPLACE, "/Objects/Demo/Model/Other")]
    fixes += fixer.propose_prefix_fixes(project, broken)[0]

    real_replace = os.replace
    calls = []

    def failing_replace(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("disque plein")
        return real_replace(src, dst)

    monkeypatch.setattr(fixer.os, "replace", failing_replace)
    with pytest.raises(fixer.FixError, match="restored|restaurés"):
        fixer.apply_fixes(project, fixes, backup_dir=str(tmp_path / "bk"))
    assert {p: p.read_bytes() for p in (model, ui)} == before


def test_quotes_added_when_needed():
    assert fixer._replace_value("  Value: a", "a", "@b", "x") == "  Value: '@b'"
    assert fixer._replace_value('  Value: "a"', "a", "b", "x") == '  Value: "b"'
    with pytest.raises(fixer.FixError):
        fixer._replace_value("  Value: abc", "ab", "x", "x")  # plus de remplacement partiel
