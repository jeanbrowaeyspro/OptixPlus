# OptixPlus — consignes pour Claude

Le cahier des charges complet est dans [docs/PROMPT_DEVELOPPEMENT.md](docs/PROMPT_DEVELOPPEMENT.md). Il fait foi : toute décision qui s'en écarte est d'abord discutée avec Jean.

## Projet

OptixPlus réunit quatre utilitaires FactoryTalk Optix (Log Reader, Link Checker, Compare, Auto Validate) en une seule application PySide6. Les dépôts sources voisins (`..\pyFTOLogReader`, `..\optix_linkcheck`, `..\FTOCompare`, `..\pyFTOAutoDeploy`) sont **en lecture seule**.

## Environnement

- Environnement virtuel `.venv` (Python 3.14), dépendances épinglées dans `requirements*.txt`. PySide6 est imposé en 6.11.1 par PySide6-QtAds.
- Installer : `.venv\Scripts\python -m pip install -r requirements-dev.txt -e .`
- Tests : `.venv\Scripts\python -m pytest -n auto` (répartis sur tous les cœurs ; sans `-n auto` pour un seul fichier ou un seul test)
- Tests rangés par fonctionnalité : `tests/common`, `tests/shell`, `tests/update` et un dossier par outil (`autovalidate`, `compare`, `linkcheck`, `logreader`). Fixtures communes dans `tests/conftest.py` (`make_controller`, `controller`, `message_boxes`), aides dans `tests/helpers` (`wait_until` : attendre une condition, jamais un délai fixe). `-m "not slow"` écarte les tests lents ; les tests `couple_reel` de la Comparaison ne tournent qu'avec `OPTIXPLUS_COMPARE_DATA` (données hors dépôt).
- Traductions : `.venv\Scripts\python tools\i18n_check.py`
- Icônes : `.venv\Scripts\python tools\make_icon.py`

## Règles

- **Ne jamais afficher de fenêtre sur l'écran de Jean sans sa permission.** Les tests et les captures tournent hors écran (`QT_QPA_PLATFORM=offscreen`, `QWidget.grab()`, et `QT_QPA_FONTDIR=C:/Windows/Fonts` pour que le texte s'affiche dans les captures). Un lancement visible (tray, focus réel) se demande d'abord.
- Français pour les commentaires, docstrings, messages de log et documentation ; noms de symboles en anglais.
- **Textes de l'interface écrits en anglais** dans le code via `tr("…")` / `tr_n(…)` (module `optixplus.common.i18n`), traduits dans `src/optixplus/i18n/fr.json`. Traduire à l'affichage, jamais dans une constante de module : une constante marque son texte avec `tr_noop("…")` (extrait par le contrôle, traduit plus tard par `tr(variable)`). Ne pas utiliser `_` comme nom de fonction de traduction. Un test échoue s'il manque une traduction française.
- Langue par défaut : celle de Windows (français pour toute variante fr-*, anglais sinon). Le changement de langue est appliqué à chaud en **reconstruisant la fenêtre** : tout est rouvert **en l'état** : chaque outil implémente `snapshot()` / `restore()` (`ToolModule`) avec l'état complet de sa page, saisies non enregistrées comprises ; `snapshot()` renvoie `None` seulement s'il ne peut pas être reconstruit (traitement en cours), la fermeture passe alors par `can_close()`. Tout nouvel outil doit avoir un test de reconstruction en l'état. Ne jamais connecter une fonction anonyme à un signal durable (service) pour mettre à jour un widget ou une action : utiliser une méthode d'un QObject (déconnexion automatique à sa destruction), par exemple `CheckedSync`.
- `core/` sans Qt et testable seul ; `ui/` sans logique métier.
- Lecture des projets Optix : toujours par `common/optix` (`project` pour le dossier et le `.optix`, `text` pour les fichiers à l'octet près, `scanner` pour l'index des nœuds d'un fichier, `tree` pour l'arbre de tout le projet sans PyYAML). Toute évolution de `tree` garde l'égalité nœud par nœud avec PyYAML (`tests/common/test_optix_tree.py`) ; un fichier hors du format généré par FT Optix est relu par PyYAML.
- Tout traitement long dans un thread (`common.workers.TaskWorker`), avec progression et annulation ; jamais dans le thread de l'interface ; jamais de `QThread.terminate()`.
- Pas de `print` : `logging`, loggers sous `optixplus.*`.
- Aucune écriture disque sans action explicite de l'utilisateur ; écriture multi-fichiers en tout ou rien, avec sauvegarde, relecture et hash.
- Thème : couleurs uniquement depuis `common.theme` ; un widget suit les changements de thème par `theme.follow(self, self._slot)`, et tout autre signal durable par `signals.follow(signal, self, self._slot)` (jamais un `connect` direct, qui survit au widget détruit) ; une boîte de dialogue gardée en référence passe par `signals.track(owner, "attribut", boîte)` ; ne jamais fixer un fond sans fixer le texte (Windows de Jean en mode sombre). Aucune police ni feuille de style globale posée par un outil.
- Un nouvel outil = un paquet `modules/<id>/` + une entrée `ModuleSpec` dans `modules/__init__.py`. La coquille (`shell/`) ne connaît aucun outil par son nom : ce qu'elle propose pour un outil passe par les champs de `ModuleSpec` (`opens_projects`, `controller_action`, `settings_path` pour sa catégorie de la fenêtre Paramètres…).
- Une action de la barre d'outils de l'outil n'est jamais dupliquée par un bouton dans la page.
- Chaque action de barre d'outils a une infobulle qui dit **sur quoi elle porte** (lignes sélectionnées uniquement, tout le projet…).
- Icônes : `icons.themed_icon(nom)` pour les SVG de `resources/icons` ; une action de barre d'outils utilise `icons.themed_action(action, nom)` pour être recolorée au changement de thème.
- Données sans schéma (historique, arbitrages…) : `settings.store(nom)` ou `KeyValueStore` (même interface que `QSettings`) ; jamais le registre.
- Réglages : une dataclass de section (attribut `SECTION`) lue par `Settings.section()` ; valeurs validées au chargement.
- Commits petits, messages en français ; pas de push sans demande de Jean.
