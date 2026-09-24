"""Rapport des tests pour GitHub Actions : chaque échec devient une annotation lisible sans connexion.

Usage (étape du workflow, après pytest --junitxml=pytest.xml) : python tools/ci_report.py pytest.xml
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def main(path: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::error title=Rapport pytest illisible::{exc}")
        return 0
    count = 0
    for case in root.iter("testcase"):
        for problem in list(case.findall("failure")) + list(case.findall("error")):
            count += 1
            if count > 45:  # GitHub garde au plus 50 annotations par tâche
                continue
            name = f"{case.get('classname')}.{case.get('name')}"
            detail = (problem.get("message") or "") + "\n" + (problem.text or "")
            detail = detail.strip()[-1500:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title={name}::{detail}")
    print(f"{count} test(s) en échec")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "pytest.xml"))
