# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller d'OptixPlus : mode « onedir », sans console.

Le mode « onedir » démarre sans décompression et déclenche moins d'alertes
d'antivirus qu'un exécutable unique. Les modules Qt que l'application n'utilise pas
sont exclus (reprise des listes de Log Reader et de Compare) ; restent QtCore,
QtGui, QtWidgets, QtSvg (icônes) et QtNetwork (instance unique), plus QtAds.

Ne pas lancer directement : ``python tools/build.py`` prépare la date de build, le
CHANGELOG embarqué et les informations de version Windows avant d'appeler PyInstaller.
"""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")
PACKAGE = os.path.join(SRC, "optixplus")
BUILD = os.path.join(ROOT, "build")

EXCLUDED_QT = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtGraphs", "PySide6.QtHelp",
    "PySide6.QtHttpServer", "PySide6.QtLocation", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtNetworkAuth",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio", "PySide6.QtSql", "PySide6.QtStateMachine",
    "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets", "PySide6.QtXml",
]
EXCLUDED_OTHER = [
    "PIL", "tkinter", "unittest", "pydoc_data", "pytest", "_pytest", "setuptools",
    "numpy", "matplotlib", "pandas", "IPython",
]

a = Analysis(
    [os.path.join(ROOT, "installer", "entry.py")],
    pathex=[SRC],
    binaries=[],
    # Ressources dans le paquet lui-même : paths.resource_path() les retrouve au même
    # endroit relatif, avec ou sans PyInstaller.
    datas=[
        (os.path.join(PACKAGE, "resources"), os.path.join("optixplus", "resources")),
        (os.path.join(PACKAGE, "i18n"), os.path.join("optixplus", "i18n")),
    ],
    # Outils chargés à la demande par leur chemin d'import (ModuleSpec.import_path).
    hiddenimports=collect_submodules("optixplus"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_QT + EXCLUDED_OTHER,
    noarchive=False,
    optimize=0,
)


# Fichiers embarqués par les hooks de PySide6 mais inutiles ici (environ 40 Mo) :
# - opengl32sw.dll : OpenGL logiciel, sans objet pour une interface Widgets ;
# - la pile TLS de Qt (et son OpenSSL en double) : les requêtes HTTPS passent par
#   urllib, qui utilise l'OpenSSL de Python (libssl-3.dll / libcrypto-3.dll) ;
# - les traductions de Qt autres que le français, et les formats d'image non utilisés
#   (seuls SVG, ICO et PNG, intégré à QtGui, servent) ;
# - les plateformes autres que Windows et « offscreen » (rendu hors écran des tests).
import re

_PRUNE = re.compile(
    r"(^|[\\/])opengl32sw\.dll$"
    r"|(^|[\\/])(libssl|libcrypto)-3-x64\.dll$"
    r"|[\\/]plugins[\\/](tls|networkinformation|generic)[\\/]"
    r"|[\\/]plugins[\\/]platforms[\\/](qdirect2d|qminimal)\.dll$"
    r"|[\\/]plugins[\\/]imageformats[\\/]q(gif|icns|jpeg|tga|tiff|wbmp|webp)\.dll$"
    r"|[\\/]translations[\\/](?!qtbase_fr\.qm$|qt_fr\.qm$)[^\\/]+\.qm$",
    re.IGNORECASE,
)


def _keep(entry) -> bool:
    return not _PRUNE.search(entry[0])


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OptixPlus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=os.path.join(PACKAGE, "resources", "icons", "app.ico"),
    version=os.path.join(BUILD, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OptixPlus",
)
