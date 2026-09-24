"""Page des résultats : bandeau, arbre des fichiers, résumé sémantique, vues spécialisées, recherche.

Les pages affichent la comparaison partagée (fixture ``window``) et les tests ne vérifient que
le câblage de l'interface ; le contenu des écarts est vérifié par les tests du cœur.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from optixplus.modules.compare.core.analysis import Comparison
from optixplus.modules.compare.ui.results_page import ROLE_KIND, branche_attendus
from optixplus.modules.compare.ui.semantic_view import SemanticModel
from optixplus.modules.compare.ui.specialized.views import SpecializedTabs

from .conftest import TAGS, find_item, wait_until


def test_bandeau_et_arbre(window) -> None:
    banner = window.results_page.banner.label.text()
    assert "1.3.2.9-Stable" in banner and "14</b> fichiers comparés" in banner
    assert "3</b> ajouts runtime" in banner and "4</b> branche projet" in banner and "3</b> valeurs modifiées" in banner
    assert "1 YAML orphelin" in banner

    tree = window.results_page.tree
    root = tree.topLevelItem(0)
    assert root.text(0) == "Tous les fichiers" and root.text(1) == "10"
    tags = find_item(root, "Tags.yaml")
    assert tags is not None and tags.text(1) == "3" and tags.text(2) == "mixte"
    assert find_item(root, "Orphelin.yaml").text(2) == "projet seul"
    assert find_item(root, "logo.svg") is None, "filtre « divergences seules »"

    attendus = [tree.topLevelItem(k) for k in range(tree.topLevelItemCount()) if tree.topLevelItem(k).text(0) == branche_attendus()]
    assert len(attendus) == 1 and not attendus[0].isExpanded()
    assert attendus[0].data(0, ROLE_KIND) == "attendus"
    noms = {attendus[0].child(k).text(0) for k in range(attendus[0].childCount())}
    assert "IHM_Demo.optix" in noms and "ApplicationFiles/RetentivityStorage.db" in noms


def test_filtres_de_l_arbre(window) -> None:
    page = window.results_page
    page.filter_combo.setCurrentIndex(1)  # tout
    assert find_item(page.tree.topLevelItem(0), "logo.svg") is not None
    page.search.setText("tags")
    root = page.tree.topLevelItem(0)
    assert find_item(root, "Tags.yaml") is not None and find_item(root, "Model.yaml") is None


def test_resume_semantique_pilote_par_l_arbre(window) -> None:
    page = window.results_page
    sem = page.semantic
    assert sem.visible_count() == 10 and sem.model.rowCount() == 12
    assert not sem.table.isColumnHidden(SemanticModel.COL_FICHIER)

    page.tree.setCurrentItem(find_item(page.tree.topLevelItem(0), "Tags.yaml"))
    assert sem.visible_count() == 3 and sem.table.isColumnHidden(SemanticModel.COL_FICHIER)
    sem.table.selectRow(0)
    row = sem.current_row()
    assert row is not None and row.rel.endswith("Tags.yaml")
    assert "+ " in sem.detail.toPlainText() and "Acquit_Z1" in sem.detail.toPlainText()

    page.tree.setCurrentItem(find_item(page.tree.topLevelItem(0), "Model.yaml"))
    assert sem.visible_count() == 1, "l'Id non significatif est masqué"
    sem.show_all.setChecked(True)
    assert sem.visible_count() == 2
    sem.search.setText("avecscanner")
    assert sem.visible_count() == 1
    sem.search.setText("")
    sem.show_all.setChecked(False)

    page.tree.setCurrentItem(find_item(page.tree.topLevelItem(0), "Nodes"))
    assert sem.visible_count() == 9


def test_modele_semantique_affichage(window) -> None:
    sem = window.results_page.semantic
    window.results_page.tree.setCurrentItem(find_item(window.results_page.tree.topLevelItem(0), "Model.yaml"))
    sem.show_all.setChecked(True)
    model = sem.model
    textes = {model.index(r, SemanticModel.COL_NOEUD).data(): model.index(r, SemanticModel.COL_SENS).data() for r in range(model.rowCount())}
    assert textes["AvecScanner"].endswith("valeur modifiée")
    assert textes["Enum_Taille"].endswith("branche projet")
    genres = {model.index(r, SemanticModel.COL_GENRE).data() for r in range(model.rowCount())}
    assert genres == {"valeur", "identifiant"}


def test_resume_semantique_pilote_diff_et_vues(window) -> None:
    page = window.results_page
    tree = page.tree
    tree.setCurrentItem(find_item(tree.topLevelItem(0), "Tags.yaml"))
    assert page.diff.nb_hunks() == 3 and page.specialized.currentWidget() is page.specialized.tags
    page.semantic.table.selectRow(2)
    assert page.semantic.current_row() is not None
    assert page.diff.current_hunk() == 2
    tree.setCurrentItem(tree.topLevelItem(0))
    page.semantic.table.sortByColumn(4, Qt.SortOrder.AscendingOrder)
    page.semantic.table.selectRow(0)
    row = page.semantic.current_row()
    assert row is not None and page.diff.title.text().startswith(f"<b>{row.rel}</b>")


def test_onglet_recherche_pilote_la_vue_diff(window) -> None:
    page = window.results_page
    view = page.search_view
    view.input.setText("Acquit_Z1")
    view.start()
    assert wait_until(lambda: view.button.isEnabled() and not view.worker.isRunning())
    assert view.model.rowCount() == 2 and "2 occurrence(s)" in view.status.text()
    assert page.show_hit("runtime", TAGS, 21)
    assert page.tabs.currentWidget() is page.diff
    row = page.diff.table.currentIndex().row()
    assert page.diff.model.rows[row].b_no == 21 and not page.diff.fold_box.isChecked()
    # Un fichier identique des deux côtés s'ouvre aussi (diff calculé à la volée), un fichier absent non.
    assert page.show_hit("projet", "Nodes/UI/Parents/IO/IO.yaml", 1)
    assert not page.show_hit("projet", "inexistant.yaml", 1)


def test_vues_specialisees(qapp, demo: Comparison) -> None:
    tabs = SpecializedTabs()
    tabs.load(demo)
    assert tabs.tabText(0).startswith("Tags CoDeSys (6)")
    assert tabs.tags.visible_count() == 6  # écarts seuls : 3 ajouts + 1 structure projet et ses 2 membres
    tabs.tags.only_gaps.setChecked(False)
    assert tabs.tags.visible_count() == tabs.tags.model.rowCount() > 6
    tabs.tags.search.setText("Acquit")
    assert tabs.tags.visible_count() == 2

    assert tabs.tabText(1) == "Traductions (1)"
    assert tabs.translations.colonnes == ["Clé", "en-US", "fr-FR", "it-IT", "État"]
    assert tabs.translations.visible_count() == 1
    assert "[3, 4]" in tabs.translations.note.text() and "[4, 4]" in tabs.translations.note.text()

    assert tabs.tabText(2) == "Types utilisateur (1)"
    assert tabs.types.visible_count() == 1
    assert tabs.types.proxy.index(0, 1).data() == "IType_Div_BP_Prog", "seul le type retiré par le runtime est affiché"

    assert tabs.stats.model.rowCount() >= 7 and not tabs.stats.only_gaps.isChecked()
    assert tabs.netlogic.model.rowCount() == 0 and "Aucune DLL" in tabs.netlogic.note.text()

    tabs.activate_for(TAGS, demo)
    assert tabs.currentWidget() is tabs.tags
    tabs.activate_for("IHM_Demo.optix", demo)
    assert tabs.currentWidget() is tabs.stats
