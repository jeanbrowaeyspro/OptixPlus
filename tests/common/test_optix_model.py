"""Modèle commun d'un projet Optix (``common.optix.model``), indépendant des outils."""

from __future__ import annotations

import pytest

from linkcheck_fixture import make_project
from optixplus.common.optix.model import Node, OptixProject
from optixplus.common.progress import Cancelled


@pytest.fixture
def project(tmp_path):
    return OptixProject(str(make_project(tmp_path))).load()


def test_load_counts_nodes_and_files(project):
    assert project.name == "Demo"
    assert project.files_loaded >= 3
    assert len(project.all_nodes) > 10
    assert all(isinstance(n, Node) for n in project.all_nodes)


def test_node_path_and_studio_path(project):
    node = project.all_nodes[-1]
    assert node.path().startswith("/Objects/Demo/")
    assert not node.studio_path(project.name).startswith("/Objects/")
    assert project.resolve(node.path(), project.objects)[0] is node


def test_load_can_be_cancelled(tmp_path):
    folder = make_project(tmp_path)

    def cancel():
        return True

    with pytest.raises(Cancelled):
        OptixProject(str(folder)).load(cancel=cancel)
