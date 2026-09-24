"""Widgets communs : ascenseurs des tableaux et arbres."""

from __future__ import annotations

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionSlider, QTableView, QTreeView

from optixplus.common.theme import install_manager
from optixplus.common.widgets import scrollbar_below_header


def test_vertical_scrollbars_start_below_column_headers(qapp):
    """Ascenseur vertical d'un tableau ou d'un arbre : sa poignée commence sous l'en-tête."""
    install_manager(qapp, "light")  # le décalage vient de la feuille de style du thème
    model = QStandardItemModel(200, 3)
    for view in (QTableView(), QTreeView()):
        scrollbar_below_header(view)
        view.setModel(model)
        view.resize(400, 200)
        view.show()
        qapp.processEvents()
        header = view.horizontalHeader() if isinstance(view, QTableView) else view.header()
        bar = view.verticalScrollBar()
        bar.setValue(0)
        option = QStyleOptionSlider()
        bar.initStyleOption(option)
        handle = bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option, QStyle.SubControl.SC_ScrollBarSlider, bar)
        top = bar.mapTo(view, handle.topLeft()).y()
        assert top >= header.mapTo(view, header.rect().topLeft()).y() + header.height()
        view.close()
