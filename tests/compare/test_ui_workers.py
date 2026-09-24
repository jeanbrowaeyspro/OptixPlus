"""Thread d'analyse : l'issue (succès, annulation, échec) remonte par un seul signal."""

from __future__ import annotations

from pathlib import Path

import pytest

from optixplus.modules.compare.ui.workers import CompareWorker

from .conftest import PROJET, RUNTIME, wait_until


@pytest.mark.parametrize("issue", ["succes", "annulation", "echec"])
def test_issue_du_thread(qapp, tmp_path: Path, issue: str) -> None:
    runtime = tmp_path / "absent" if issue == "echec" else RUNTIME
    worker = CompareWorker(runtime, PROJET)
    outcomes: list[tuple[str, object]] = []
    steps: list[tuple] = []
    worker.progressed.connect(lambda *args: steps.append(args))
    worker.succeeded.connect(lambda result: outcomes.append(("succes", result)))
    worker.cancelled.connect(lambda: outcomes.append(("annulation", None)))
    worker.failed.connect(lambda error: outcomes.append(("echec", error)))
    if issue == "annulation":
        worker.request_cancel()
    worker.start()
    assert wait_until(lambda: outcomes and worker.isFinished())

    assert [kind for kind, _ in outcomes] == [issue]
    if issue == "succes":
        assert {s[0] for s in steps} == {"inventaire", "hash", "diff", "analyse"}
    elif issue == "echec":
        assert "Traceback" in outcomes[0][1]
