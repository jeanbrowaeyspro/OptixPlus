# OptixPlus

Boîte à outils FactoryTalk Optix réunie en une seule application Windows :

- **Log Reader** : suivi en direct du journal runtime des automates, filtres, export ;
- **Link Checker** : détection et réparation des DynamicLink cassés d'un projet ;
- **Compare** : comparaison runtime ↔ projet et application sécurisée des correctifs ;
- **Auto Validate** : validation automatique de la boîte « Le projet existe déjà » de FT Optix Studio.

Une fois installé, OptixPlus reste dans la zone de notification : son icône ouvre la fenêtre principale, et la surveillance de FT Optix Studio tourne en arrière-plan.

## Installation

Télécharger `OptixPlus-Setup-X.Y.Z.exe` depuis les [Releases](https://github.com/jeanbrowaeyspro/OptixPlus/releases) et le lancer. L'installation se fait dans `C:\Program Files\OptixPlus`, pour tous les utilisateurs du poste (confirmation administrateur demandée). Elle propose :

- de démarrer OptixPlus avec Windows (coché) ;
- si les anciens outils sont détectés, d'importer leurs réglages et de retirer le démarrage automatique de l'ancien OptixAutoValidate (décochés). Rien n'est supprimé des anciens outils.

**Version portable** : `OptixPlus-Portable-X.Y.Z.exe`, publiée avec chaque release, se lance sans installation (mode découverte). Pas d'icône dans la zone de notification ni de démarrage avec Windows, rien n'est écrit dans le registre, et la surveillance de FT Optix Studio ne tourne que tant que la fenêtre est ouverte. Les mises à jour ouvrent la page de téléchargement.

L'exécutable n'est pas signé : Windows SmartScreen peut afficher « Windows a protégé votre ordinateur ». Cliquer sur « Informations complémentaires », puis « Exécuter quand même ». L'empreinte SHA-256 publiée avec chaque release permet de vérifier le fichier.

Les mises à jour se font ensuite depuis OptixPlus (menu Aide, tray ou Paramètres) : l'installateur est téléchargé, vérifié par son empreinte, puis installé en silencieux.

## Ressources

Mesures sur l'exécutable construit (Windows 11) :

| Mesure | Valeur |
|---|---|
| Installateur | 23,6 Mo |
| Application installée | 70,6 Mo |
| Démarrage jusqu'à la fenêtre prête | 0,6 s |
| Mémoire, fenêtre ouverte sur l'accueil | 74 à 80 Mo |
| Mémoire, un outil ouvert | 77 à 87 Mo |
| Processeur au repos | environ 0,2 % d'un cœur |

## Développement

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -e .
.venv\Scripts\python -m pytest
```

Tests sur des données réelles, facultatifs : `OPTIXPLUS_COMPARE_DATA` (dossier d'un couple réel pour Compare, avec son `optixplus_expected.json`) et `OPTIXPLUS_OPTIX_SAMPLES` (dossiers de projets Optix séparés par `;`, lus par la lecture directe et par PyYAML, qui doivent donner le même résultat). Les données ne sont jamais modifiées : les tests travaillent sur des copies.

Lancer depuis les sources : `.venv\Scripts\python -m optixplus` (mode découverte, sans tray) ou `--installe` (mode installé, avec tray). `--outil <id>` ouvre directement un outil (`logreader`, `linkcheck`, `compare`, `autovalidate`).

Réglages et journaux : `%APPDATA%\OptixPlus`.

## Construction et publication

```bash
.venv\Scripts\python tools\build.py                 # dist\OptixPlus\ + dist\OptixPlus-Setup-X.Y.Z.exe (+ .sha256)
.venv\Scripts\python tools\build.py --no-installer  # exécutable seul
```

Pré-requis : Inno Setup 6 (`winget install JRSoftware.InnoSetup`). Pour publier : renommer la section `[Non publié]` du CHANGELOG en `[X.Y.Z] - date`, mettre `__version__` à jour dans `src/optixplus/version.py`, puis pousser le tag `vX.Y.Z` : le workflow `.github/workflows/release.yml` teste, construit et crée la release.

## Langues

L'interface suit la langue de Windows (français ou anglais) ; un réglage permet de la forcer, avec effet immédiat. Les textes sources sont en anglais, le catalogue français est `src/optixplus/i18n/fr.json`. `tools/i18n_check.py` signale les traductions manquantes.

## Auteur

Jean Browaeys — Automaticien Indépendant

Propulsé par Claude Opus 5.5.
