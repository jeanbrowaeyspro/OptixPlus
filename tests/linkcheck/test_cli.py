"""Link Checker en ligne de commande (``python -m optixplus linkcheck``), dans un vrai processus."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from linkcheck_fixture import make_project
from optixplus.common import paths


@pytest.mark.slow
@pytest.mark.parametrize(("language", "expected"), [("en", "Target :"), ("fr", "Cible :")])
def test_cli_lists_broken_links_in_the_configured_language(tmp_path, language, expected):
    project = make_project(tmp_path)
    appdata = tmp_path / "appdata"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "APPDATA": str(appdata)}
    settings_file = appdata / paths.settings_path().relative_to(os.environ["APPDATA"])
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(json.dumps({"general": {"language": language}}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "optixplus", "linkcheck", str(project)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Demo" in result.stdout
    assert result.stdout.count("OldProject") >= 3
    assert expected in result.stdout
