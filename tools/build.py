"""Construit OptixPlus : application installée (installateur Inno Setup) et exécutable portable.

Usage :
    .venv\\Scripts\\python tools\\build.py                  # installateur + portable
    .venv\\Scripts\\python tools\\build.py --no-installer   # application (onedir) seule
    .venv\\Scripts\\python tools\\build.py --no-portable    # sans l'exécutable portable
    .venv\\Scripts\\python tools\\build.py --notes 1.0.0    # notes de version (section du CHANGELOG)

Résultats dans ``dist/`` : ``OptixPlus/`` (l'application), ``OptixPlus-Setup-X.Y.Z.exe``,
``OptixPlus-Portable-X.Y.Z.exe`` (mode découverte, un seul fichier) et un ``.sha256`` pour
chacun. Le même script sert au workflow de publication GitHub.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "optixplus"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
BUILD_INFO = PACKAGE / "_build_info.py"
EMBEDDED_CHANGELOG = PACKAGE / "resources" / "CHANGELOG.md"

sys.path.insert(0, str(SRC))
from optixplus.update import changelog  # noqa: E402
from optixplus.version import APP_NAME, AUTHOR, __version__  # noqa: E402

ISCC_CANDIDATES = [
    Path(os.environ.get("ISCC", "")),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
]


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    core = version.split("-")[0].split("+")[0]
    major, minor, patch = (int(p) for p in core.split("."))
    return major, minor, patch, 0


def write_version_info() -> Path:
    """Informations de version Windows (propriétés du fichier .exe)."""
    numbers = version_tuple(__version__)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', {AUTHOR!r}),
      StringStruct('FileDescription', {APP_NAME + ' - Boîte à outils FactoryTalk Optix'!r}),
      StringStruct('FileVersion', {__version__!r}),
      StringStruct('InternalName', {APP_NAME!r}),
      StringStruct('LegalCopyright', {'© ' + str(datetime.date.today().year) + ' ' + AUTHOR!r}),
      StringStruct('OriginalFilename', {APP_NAME + '.exe'!r}),
      StringStruct('ProductName', {APP_NAME!r}),
      StringStruct('ProductVersion', {__version__!r})])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
"""
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def prepare_sources(portable: bool = False) -> None:
    """Date de build, marque « portable » et CHANGELOG embarqués (retirés après la construction)."""
    BUILD_INFO.write_text(
        f'BUILD_DATE = "{datetime.date.today().isoformat()}"\nPORTABLE = {portable}\n', encoding="utf-8"
    )
    shutil.copyfile(ROOT / "CHANGELOG.md", EMBEDDED_CHANGELOG)


def clean_sources() -> None:
    BUILD_INFO.unlink(missing_ok=True)
    EMBEDDED_CHANGELOG.unlink(missing_ok=True)


def run_pyinstaller(portable_name: str = "") -> Path:
    log(f"PyInstaller {portable_name or APP_NAME} {__version__}")
    env = {**os.environ, "OPTIXPLUS_PORTABLE": portable_name}
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
            str(ROOT / "installer" / "OptixPlus.spec"),
        ],
        check=True,
        cwd=ROOT,
        env=env,
    )
    if portable_name:
        exe = DIST / f"{portable_name}.exe"
        if not exe.is_file():
            raise SystemExit("exécutable portable absent après PyInstaller")
        return exe
    app_dir = DIST / APP_NAME
    if not (app_dir / f"{APP_NAME}.exe").is_file():
        raise SystemExit("exécutable absent après PyInstaller")
    return app_dir


def find_iscc() -> Path:
    for candidate in ISCC_CANDIDATES:
        if candidate.name == "ISCC.exe" and candidate.is_file():
            return candidate
    raise SystemExit("Inno Setup 6 (ISCC.exe) introuvable : winget install JRSoftware.InnoSetup")


def run_inno_setup(app_dir: Path) -> Path:
    iscc = find_iscc()
    log(f"Inno Setup ({iscc})")
    numeric = ".".join(str(n) for n in version_tuple(__version__))
    subprocess.run(
        [
            str(iscc), "/Q",
            f"/DAppVersion={__version__}",
            f"/DAppVersionNumeric={numeric}",
            f"/DSourceDir={app_dir}",
            f"/DOutputDir={DIST}",
            str(ROOT / "installer" / "OptixPlus.iss"),
        ],
        check=True,
        cwd=ROOT,
    )
    setup = DIST / f"{APP_NAME}-Setup-{__version__}.exe"
    if not setup.is_file():
        raise SystemExit("installateur absent après Inno Setup")
    return setup


def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_name(path.name + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    log(f"SHA-256 {digest}")
    return checksum


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def release_notes(version: str) -> str:
    """Section du CHANGELOG pour ``version`` (notes de la release GitHub)."""
    sections = changelog.parse((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    for section in sections:
        if section.title == version:
            return section.body.strip() + "\n"
    raise SystemExit(f"aucune section [{version}] dans CHANGELOG.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-installer", action="store_true", help="construire l'application (onedir) seule")
    parser.add_argument("--no-portable", action="store_true", help="ne pas construire l'exécutable portable")
    parser.add_argument("--notes", metavar="VERSION", help="afficher les notes de version et s'arrêter")
    args = parser.parse_args(argv)

    if args.notes:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(release_notes(args.notes))
        return 0

    write_version_info()
    prepare_sources()
    try:
        app_dir = run_pyinstaller()
    finally:
        clean_sources()
    log(f"Application : {app_dir} ({folder_size(app_dir) / 1e6:.1f} Mo)")
    if args.no_installer:
        return 0
    setup = run_inno_setup(app_dir)
    write_checksum(setup)
    log(f"Installateur : {setup} ({setup.stat().st_size / 1e6:.1f} Mo)")
    if not args.no_portable:
        prepare_sources(portable=True)
        try:
            portable = run_pyinstaller(f"{APP_NAME}-Portable-{__version__}")
        finally:
            clean_sources()
        write_checksum(portable)
        log(f"Portable : {portable} ({portable.stat().st_size / 1e6:.1f} Mo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
