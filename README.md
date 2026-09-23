# OptixPlus

Boîte à outils FactoryTalk Optix réunie en une seule application Windows :

- **Log Reader** : suivi en direct du journal runtime des automates, filtres, export ;
- **Link Checker** : détection et réparation des DynamicLink cassés d'un projet ;
- **Compare** : comparaison runtime ↔ projet et application sécurisée des correctifs ;
- **Auto Validate** : validation automatique de la boîte « Le projet existe déjà » de FT Optix Studio.

Une fois installé, OptixPlus reste dans la zone de notification : son icône ouvre la fenêtre principale, et la surveillance de FT Optix Studio tourne en arrière-plan.

> Développement en cours : le socle (phase 0) est en place, les outils sont intégrés phase par phase.

## Développement

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -e .
.venv\Scripts\python -m pytest
```

Lancer depuis les sources : `.venv\Scripts\python -m optixplus` (mode découverte, sans tray) ou `--installe` (mode installé, avec tray). `--outil <id>` ouvre directement un outil (`logreader`, `linkcheck`, `compare`, `autovalidate`).

Réglages et journaux : `%APPDATA%\OptixPlus`.

## Langues

L'interface suit la langue de Windows (français ou anglais) ; un réglage permet de la forcer. Les textes sources sont en anglais, le catalogue français est `src/optixplus/i18n/fr.json`. `tools/i18n_check.py` signale les traductions manquantes.

## Auteur

Jean Browaeys — Automaticien Indépendant

Propulsé par Claude Opus 5.5.
