# OptixPlus — prompt de développement

> Prompt rédigé par Claude pour lui-même, à valider par Jean avant tout développement.
> Il fait foi pour toute la durée du projet. Toute décision qui s'en écarte est d'abord discutée avec Jean.

## 1. Mission

Fusionner quatre utilitaires FactoryTalk Optix écrits en Python / PySide6 en **une seule application Windows installable, « OptixPlus »**, dans le dépôt `OptixPlus`, voisin des quatre outils sources (remote public `https://github.com/jeanbrowaeyspro/OptixPlus`).

| Outil source | Dossier | Rôle |
|---|---|---|
| Log Reader | `..\pyFTOLogReader` | Suivi en direct de `FTOptixRuntime.0.log` sur les automates (SMB), filtres, surlignage, export xlsx/csv |
| Link Checker | `..\optix_linkcheck` | Détection et correction des DynamicLink cassés dans les YAML d'un projet |
| Compare | `..\FTOCompare` | Comparaison runtime ↔ projet, plan de décision, application sécurisée des correctifs |
| Auto Validate | `..\pyFTOAutoDeploy` | Validation automatique du popup « Le projet existe déjà » de FT Optix Studio (tray) |

Les quatre dépôts sources sont **en lecture seule** : on y copie du code, on ne les modifie jamais.

Chaque fonctionnalité existante doit être conservée, sauf si Jean décide explicitement de la retirer. Les défauts connus (§11) sont corrigés pendant le portage.

## 2. Décisions validées avec Jean

1. **Une seule application, un seul processus.** L'icône du tray sert de lanceur de la fenêtre principale.
2. **Icône** : anneau **rond** violet `#7C3AED` (variante A). Un « + » violet cerclé d'un liseré blanc fin (environ 2,5 unités sur une icône de 100) est **centré sur le tracé de l'anneau**, en bas à droite à 45°, comme le « x » du logo FT Optix. Fond transparent. Il existe aussi une variante grise (`#A1A1AA`) pour la surveillance suspendue.
3. **Navigation** : barre latérale verticale à gauche (Accueil, Log Reader, Link Checker, Compare, Auto Validate, puis Paramètres en bas). Sous le menu, une barre d'outils **contextuelle** affiche les actions de l'outil actif. Le menu « Outils » reprend la même navigation, avec les raccourcis Ctrl+1 à Ctrl+5.
4. **Distribution** : un installateur Windows classique d'abord. La version portable (« mode découverte ») viendra plus tard, mais l'architecture doit la permettre dès maintenant (§5).
5. **Mises à jour** : via les Releases GitHub du dépôt public.
6. **Défauts repérés** : corrigés pendant la fusion.
7. **Langues** : l'interface est bilingue français/anglais. **Par défaut, la langue suit Windows** : français si la langue d'affichage de Windows est le français, anglais dans tous les autres cas. Les clés de traduction sont en anglais. Tout texte visible passe par le système de traduction (§8).
8. **Migration depuis les anciens outils** : l'installateur la **propose**, sans jamais l'imposer. Deux cases décochées par défaut : « Reprendre les réglages des anciens outils » et « Désactiver le démarrage automatique de l'ancien OptixAutoValidate ». Rien n'est fait sans accord explicite.
9. **Log Reader multi-logs** : onglets détachables et fractionnables comme dans Visual Studio. On peut regrouper les onglets côte à côte (gauche/droite ou haut/bas), les sortir dans des fenêtres flottantes et les placer sur un autre écran. C'est **uniquement de l'organisation visuelle** : aucune comparaison automatique entre logs.

## 3. Conventions (héritées de `FTOCompare/CLAUDE.md`, étendues à tout le projet)

- **Français** pour les commentaires, docstrings, messages de log et documentation. **Noms de symboles en anglais.** Les textes visibles de l'interface sont écrits en anglais dans le code et traduits via `fr.json` (§8).
- Python ≥ 3.11, avec type hints partout. Dépendances d'exécution limitées à PySide6, PySide6-QtAds et openpyxl (plus PyYAML tant que Link Checker l'utilise). Versions **épinglées** dans `requirements.txt`.
- **Séparation stricte** : chaque `core/` est sans Qt et testable seul ; chaque `ui/` est sans logique métier.
- **Tout traitement long** (lecture de fichier, analyse, écriture, réseau) tourne dans un `QThread` : progression visible (étape, fichier en cours, compteur), annulation possible, **jamais dans le thread de l'interface**.
- Pas de `print`. On utilise `logging`, avec un logger par module sous `optixplus.*` et un panneau Journal unique dans l'application.
- **Aucune écriture disque** sans action explicite de l'utilisateur. Avant toute écriture dans un projet : sauvegarde, puis relecture et vérification par hash, puis restauration au premier échec. Une écriture multi-fichiers est **tout ou rien**.
- YAML Optix : lecture en binaire, séparateur de ligne et BOM détectés puis conservés. On compare par hash, jamais par taille. Parcours sans limite de profondeur, sans récursion Python profonde.
- **Thème** : ne jamais fixer une couleur de fond sans fixer celle du texte (le Windows de Jean est en mode sombre). Aucune couleur codée en dur dans les widgets : tout vient de la palette du thème.
- Commits petits et fréquents, messages en français, un sujet par commit. Pas de push sans demande de Jean.
- Un `CLAUDE.md` à la racine d'OptixPlus reprend ces conventions pour les sessions futures.

## 4. Architecture cible

```
OptixPlus/
  pyproject.toml            # métadonnées, dépendances, config pytest
  requirements.txt          # exécution, épinglé (PySide6==6.11.1 imposé par PySide6-QtAds 5.0.0.2)
  requirements-dev.txt      # pytest, pyinstaller, pillow
  CHANGELOG.md              # source unique des notes de version (FR ; section EN optionnelle)
  CLAUDE.md, README.md
  src/optixplus/
    __main__.py             # point d'entrée
    version.py              # __version__ unique ; date de build injectée au build
    app.py                  # amorçage : mode, instance unique, IPC, thème, langue, tray
    shell/                  # tout ce qui est commun à l'interface
      main_window.py        # fenêtre principale : barre latérale + barre d'outils contextuelle + pile de pages
      sidebar.py
      home_page.py          # tableau de bord : surveillance, projets récents, automates récents, raccourcis
      tray.py               # icône du tray et son menu
      settings_dialog.py    # Paramètres unifiés : un onglet Général + un onglet par module
      about_dialog.py       # À propos
      changelog_dialog.py   # Nouveautés
      log_panel.py          # panneau Journal commun (repris de FTOCompare)
      progress_page.py      # progression + Annuler (repris de FTOCompare)
    common/
      paths.py              # _MEIPASS, %APPDATA%\OptixPlus, ressources
      settings.py           # JSON atomique, schéma versionné et validé, sections par module
      dpapi.py              # repris de Log Reader
      theme.py              # palette + QSS (base Log Reader), accent violet, Système/Clair/Sombre
      i18n.py               # traduction (§8)
      workers.py            # QThread générique : progression, annulation, retire() non bloquant
      progress.py           # Progress / Cancelled sans Qt (repris de FTOCompare)
      win32.py              # ctypes : mutex, fenêtres, SendInput, WinEventHook
      single_instance.py    # mutex + QLocalServer/QLocalSocket
      optix/                # lecture de projet Optix partagée (phase 8) : project (dossier, .optix, - File:),
                            # text (octet près), scanner (index des nœuds), tree (arbre sans PyYAML, repli PyYAML)
    modules/
      base.py               # interface ToolModule (§6)
      logreader/{core,ui}/
      linkcheck/{core,ui}/
      compare/{core,ui,report}/
      autovalidate/{core,ui}/
    update/
      github.py             # interroge l'API GitHub Releases, compare les versions
      installer.py          # télécharge, vérifie le SHA-256, lance l'installateur
    resources/              # icônes générées, CHANGELOG.md embarqué, traductions
  i18n/fr.json              # catalogue français (clés = textes anglais)
  tools/
    make_icon.py            # génère .ico et .png (normal + suspendu, 16→256 px)
    build.py                # PyInstaller en mode onedir, avec exclusions Qt
    i18n_check.py           # liste les chaînes non traduites ou orphelines
  installer/OptixPlus.iss   # script Inno Setup
  .github/workflows/release.yml  # construction et publication au push d'un tag vX.Y.Z
  tests/
```

## 5. Modes de lancement

Le mode est détecté au démarrage, dans cet ordre : argument `--decouverte` ou `--installe`, sinon présence de l'exe dans le dossier d'installation (clé `HKCU\Software\OptixPlus\InstallDir`).

- **Mode installé**, le seul livré en phase 1 :
  - le processus reste résident avec l'icône du tray et la surveillance Auto Validate ;
  - fermer la fenêtre principale **détruit** la fenêtre et ses pages pour libérer la mémoire. Si la surveillance est active, OptixPlus reste dans le tray et le signale par une bulle (il continue de valider la boîte de FT Optix Studio) ; si elle est suspendue, OptixPlus se ferme complètement ;
  - « Quitter » dans le tray arrête tout.
- **Mode découverte**, distribué en exécutable portable (`OptixPlus-Portable-X.Y.Z.exe`, un seul fichier, marqué « portable » à la construction et toujours dans ce mode) :
  - pas de tray ; la surveillance est désactivée par défaut, mais activable à la main tant que la fenêtre est ouverte ;
  - fermer la fenêtre arrête le processus ;
  - aucune écriture dans le registre, aucun démarrage automatique.
- **Instance unique** : un mutex `Local\OptixPlus_SingleInstance` et un `QLocalServer`. Un second lancement envoie sa ligne de commande à la première instance, par exemple `show`, `open-tool logreader` ou `open-controller logreader <hôte>`, puis s'arrête. La première instance affiche sa fenêtre et la met au premier plan.
- **Démarrage avec Windows** : une case dans les Paramètres, reprise de `startup.py` (clé Run `OptixPlus`) et proposée aussi par l'installateur.

## 6. Coquille et modules

- `ToolModule` (dans `modules/base.py`) décrit chaque outil :
  - `id`, titre traduit, icône, raccourci ;
  - `create_page(parent)` et `toolbar_actions()` ;
  - `on_activated()` / `on_deactivated()` pour suspendre minuteurs et rafraîchissements quand la page n'est pas visible ;
  - `can_close()`, pour demander confirmation si un traitement est en cours ;
  - `shutdown()`, pour un arrêt propre des threads (pas de `terminate()`) ;
  - `settings_page()` optionnelle.
- **Chargement à la demande** : un module n'est importé qu'à la première ouverture de sa page. Auto Validate est l'exception : son `core` est chargé au démarrage pour la surveillance, sa page non.
- Barre d'outils contextuelle : elle affiche les actions du module actif, avec le même style pour tous.
- Barre d'état commune : état de la surveillance, messages du module actif, version.
- **Journal** commun : un dock rangé dans le menu Affichage (Ctrl+J), branché sur `optixplus.*`.
- **Page d'accueil** :
  - tuiles des 4 outils ;
  - état de la surveillance, avec un interrupteur ;
  - projets Optix récents, en liste partagée par Link Checker et Compare. Un clic ouvre le projet dans l'outil choisi ;
  - automates récents : un clic ouvre le log correspondant.
- **Menus** :
  - Fichier : ouvrir un projet, ouvrir un log, Quitter ;
  - Outils ;
  - Affichage : thème, Journal ;
  - Aide : Rechercher les mises à jour, Nouveautés, À propos.
- **Tray** :
  - clic gauche : ouvrir OptixPlus ;
  - clic droit : Ouvrir OptixPlus, Ouvrir un log…, les 4 outils, Surveillance active (case à cocher), Journal de la surveillance, Paramètres…, Rechercher les mises à jour, Quitter ;
  - infobulle reprise d'Auto Validate ;
  - icône grise quand la surveillance est suspendue.

## 7. Portage des modules, point par point

### 7.1 Auto Validate

- Reprendre la logique de `watcher.py` : titres FR/EN, contrôle du processus `FTOptixStudio.exe`, prise de focus, touche Entrée, vérification, réessais, restauration du focus, notification, temporisations anti-rebond.
- **Remplacer le scrutin à 150 ms** par un `SetWinEventHook` hors contexte, sur `EVENT_OBJECT_SHOW`, `EVENT_SYSTEM_DIALOGSTART` et `EVENT_SYSTEM_FOREGROUND`, filtré sur les fenêtres de premier niveau. Garder une vérification de secours lente (environ 2 s) en cas d'événement manqué. La référence du callback ctypes est conservée.
- Mettre en cache les motifs en minuscules. Vérifier que l'astuce ALT n'envoie rien à une autre fenêtre.
- Journal dédié : rotation du fichier, conservé, mais sur un logger enfant de `optixplus` (pas de handler en double) et sans API privée pour l'effacement.
- La page du module contient les réglages et le journal de la surveillance. Les compteurs sont affichés sur l'accueil.

### 7.2 Link Checker

- Porter `model.py` et `fixer.py` dans `core/`, et `gui_qt.py` dans `ui/`. Conserver le mode CLI : `python -m optixplus linkcheck <dossier> [--fix-prefix]`.
- Corrections à apporter :
  - `apply_fixes` passe dans un worker, en tout ou rien : préparation en mémoire de toutes les modifications, puis écriture et vérification, puis rollback si un fichier échoue ;
  - annulation de l'analyse, et arrêt propre du thread à la fermeture ;
  - `_build` écrit en itératif ;
  - progression calculée sur les fichiers réellement référencés ;
  - statistique « builtin » affichée ;
  - lecture du nom de projet dans `.optix` fiabilisée ;
  - remplacement de la cible limité à la valeur exacte ;
  - plus de police ni de QSS globales propres au module.

### 7.3 Compare

- Porter `core/`, `report/` et `ui/` en conservant l'API du moteur et les **~100 tests pytest**, adaptés aux nouveaux chemins. Conserver les arbitrages mémorisés, en les migrant de QSettings vers `settings.json`.
- Corrections à apporter :
  - `build_preview()` passe dans un worker, avec progression ;
  - `Inventory.get()` passe par un index en dictionnaire ;
  - `LIBELLE_SENS` et `SYMBOLE` n'ont plus qu'une seule définition ;
  - les couleurs HTML inline viennent de la palette du thème (avec leur couleur de fond) ;
  - la mémoire des diffs est réduite (lignes gardées une seule fois et construites à la demande pour la vue).

### 7.4 Log Reader

- Porter le lecteur (`CreateFileW` en partage total, rotation, reconnexion), la découverte, `netshare`, les filtres, le surlignage, les archives, l'export et DPAPI.
- **Multi-logs** avec **PySide6-QtAds** (Qt Advanced Docking System). Si ce composant pose un problème bloquant, avertir Jean avant de passer à une implémentation maison, forcément moins complète.
  - **Un onglet = un automate.** Chaque onglet a son propre suivi, son modèle, ses filtres, sa recherche et son panneau de détail.
  - Le titre de l'onglet donne le nom de l'automate ou du projet, avec le voyant de connexion. Un badge compte les nouvelles erreurs quand l'onglet n'est pas visible.
  - Les onglets se glissent pour fractionner la zone (gauche, droite, haut, bas) ou pour sortir dans une fenêtre flottante sur un autre écran.
  - **Nouvel onglet** : Ctrl+T, bouton « + », le menu du tray ou la page d'accueil. Il ouvre le dialogue de connexion (liste des automates détectés).
  - La disposition et la liste des onglets sont enregistrées. Un paramètre « Rouvrir les logs de la session précédente », activé par défaut, les restaure.
  - Aucune comparaison automatique entre logs.
- Corrections à apporter :
  - un seul minuteur d'état partagé par tous les onglets, et seulement quand au moins un onglet est connecté ;
  - le suivi dort vraiment entre deux lectures (événement d'arrêt au lieu de réveils toutes les 100 ms) ;
  - les compteurs par niveau sont mis à jour par incréments et non recalculés à chaque lot ;
  - le texte de recherche est gardé une seule fois, et `raw` seulement s'il est utile ;
  - limite de lignes réglable par onglet ;
  - plus aucun `terminate()` : arrêt coopératif, avec `retire()` pour les lectures bloquées ;
  - la configuration est validée au chargement ;
  - un échec de DPAPI est signalé au lieu d'être silencieux ;
  - aucune adresse ni aucun identifiant par défaut : l'utilisateur saisit les siens (mots de passe chiffrés par la DPAPI).

## 8. Traduction

- On utilise un **système maison léger, commun au `core` et à l'`ui`**, car le `core` ne doit pas dépendre de Qt :
  - `from optixplus.common.i18n import tr`, puis `tr("Source text in English")` (pas de `_`, souvent pris pour « valeur ignorée ») ; une constante de module marque son texte avec `tr_noop("…")` et le traduit à l'affichage ;
  - **le texte source anglais est la clé** (bonne pratique : l'anglais est la langue de repli et le code se lit sans catalogue) ;
  - `i18n/fr.json` associe chaque texte anglais à sa traduction française ; l'anglais n'a pas besoin de catalogue ;
  - `tr_n(singulier, pluriel, n)` gère les pluriels, avec paramètres nommés : `tr_n("{n} broken link", "{n} broken links", n).format(n=n)`.
- **Conséquence pour le portage** : tous les textes visibles des quatre outils, aujourd'hui en français, sont réécrits en anglais dans le code et leur texte français actuel passe dans `fr.json`. Le rendu français doit rester identique à l'existant. Les commentaires, docstrings et messages de log internes restent en français (§3).
- **Choix de la langue** : paramètre « Langue » avec trois valeurs, `Automatique (Windows)` par défaut, `Français`, `English`.
  - En automatique : `GetUserDefaultUILanguage()` (repli sur la locale Python) ; français si la langue principale est le français (`fr-FR`, `fr-BE`, `fr-CA`, `fr-CH`…), anglais sinon.
  - Le changement s'applique **à chaud** : la fenêtre est reconstruite dans la nouvelle langue, sur le même outil, et le menu du tray est reconstruit. Tout est rouvert **en l'état** (outils ouverts, page affichée, saisies non enregistrées, boîtes de dialogue ouvertes, Paramètres sur la même catégorie) : chaque outil implémente `snapshot()` / `restore()`.
- Les boutons et dialogues standard de Qt passent par `QTranslator`, avec les `qtbase_fr.qm` fournis par PySide6 quand la langue est le français.
- L'installateur Inno Setup suit la même règle (détection automatique de la langue, FR ou EN).
- `tools/i18n_check.py` liste les chaînes non traduites et les entrées orphelines. Un test pytest échoue s'il manque une traduction française.
- `tests/test_i18n_ui.py` construit toute l'interface hors écran dans chaque langue et relève chaque texte affiché : aucun texte de l'autre langue ne doit apparaître.
- La ligne de commande (`optixplus linkcheck`) suit le même réglage de langue que la fenêtre.

## 9. Mises à jour, À propos, Nouveautés

- **Versions** : semver `X.Y.Z`, source unique `version.py`, tag Git `vX.Y.Z`. La première version publiée est la `1.0.0`.
- **Paramètres** :
  - recherche automatique activée ou non (activée par défaut) ;
  - fréquence : au démarrage, puis toutes les N heures, au choix entre quotidienne, hebdomadaire ou au démarrage seulement ;
  - option « Inclure les préversions » (désactivée) ;
  - date de la dernière vérification affichée.
- **Rechercher maintenant** : depuis le menu Aide, le tray et les Paramètres.
- **Vérification** :
  - `GET https://api.github.com/repos/jeanbrowaeyspro/OptixPlus/releases/latest` en HTTPS, via `urllib` (bibliothèque standard), dans un thread, avec un délai d'attente limité ;
  - pas d'authentification, en respectant la limite de requêtes de GitHub ;
  - aucune donnée personnelle envoyée, en dehors d'un en-tête `User-Agent: OptixPlus/<version>`.
- **Si une version est disponible** : une notification dans le tray et un dialogue qui affiche les notes de version, avec trois choix : Installer maintenant, Plus tard, Ignorer cette version.
- **Installation d'une mise à jour** :
  1. Télécharger `OptixPlus-Setup-X.Y.Z.exe` et son fichier `.sha256` depuis les assets de la release, puis vérifier l'empreinte.
  2. Lancer l'installateur avec `/SILENT /CLOSEAPPLICATIONS`, puis quitter proprement.
  3. L'installateur relance OptixPlus une seule fois, avec `--apres-maj` (pas de `/RESTARTAPPLICATIONS`, qui le relancerait une seconde fois).
- **Nouveautés** : au premier lancement d'une nouvelle version (dernière version vue enregistrée dans les réglages), afficher le dialogue Nouveautés, qui rend la section correspondante de `CHANGELOG.md` embarqué. Aide > Nouveautés le rouvre, avec l'historique complet.
- **À propos** :
  - nom, icône, version, date de build, auteur « Jean Browaeys — Automaticien Indépendant », puis la mention « Propulsé par Claude Opus 5.5 » ;
  - lien vers le dépôt GitHub ;
  - versions de Python, PySide6 et Qt ;
  - chemins des réglages et des journaux, avec un bouton pour ouvrir chacun ;
  - licences des composants tiers (Qt/PySide6 en LGPL, QtAds en LGPL, openpyxl en MIT).
- En mode découverte (plus tard), pas d'installation automatique : juste un lien de téléchargement.

## 10. Construction, installateur, publication

- **PyInstaller en mode `onedir`** : démarrage rapide, pas de décompression à chaque lancement, et moins de faux positifs d'antivirus. On reprend les exclusions de modules Qt de Log Reader et Compare et on vise l'exe le plus léger possible. L'icône est embarquée, ainsi que les versions de fichier Windows (`version_file`).
- **Inno Setup 6** (`installer/OptixPlus.iss`) :
  - installation dans `C:\Program Files\OptixPlus` pour tous les utilisateurs (`PrivilegesRequired=admin`, demande UAC), à la demande de Jean ; dossier d'installation inscrit dans `HKLM\Software\OptixPlus` ; démarrage avec Windows, reprise des anciens outils et lancements restent propres à l'utilisateur qui installe (`runasoriginaluser`) ; une installation 1.0.0 dans le profil est d'abord désinstallée, réglages gardés ;
  - raccourci dans le menu Démarrer ; raccourci sur le Bureau en option ;
  - entrée dans « Applications installées » avec un désinstalleur ;
  - instance en cours : l'installateur attend jusqu'à 15 s qu'OptixPlus se ferme (mise à jour lancée depuis l'application), puis la ferme par le gestionnaire de redémarrage de Windows (`CloseApplications=force`) ; pas d'`AppMutex`, qui ferait échouer la mise à jour silencieuse ;
  - langues FR et EN pour l'installateur ;
  - pages de tâches :
    - « Démarrer OptixPlus avec Windows » (cochée) ;
    - les deux cases de migration (décochées, §2.8), affichées seulement si un ancien outil est détecté, exécutées par OptixPlus lui-même au premier lancement via `--migrer=reglages,autovalidate` ;
  - la désinstallation supprime la clé Run. Elle **demande** s'il faut supprimer les réglages dans `%APPDATA%\OptixPlus`.
- La **migration**, si elle est cochée :
  - importe les réglages de Log Reader (`%APPDATA%\pyFTOLogReader\settings.json`), de Link Checker et de Compare (registre QSettings, clé trouvée par le nom de l'outil sous `HKCU\Software\*`, sans écrire l'ancien nom d'éditeur dans le code) et d'Auto Validate (`%APPDATA%\OptixAutoValidate\config.json`) ; une section déjà présente dans OptixPlus n'est jamais écrasée ;
  - supprime la valeur Run `OptixAutoValidate` et propose de fermer le processus s'il tourne ;
  - ne supprime aucun fichier des anciens outils.
- **Publication** : un workflow GitHub Actions (`windows-latest`) se déclenche au push d'un tag `vX.Y.Z`. Il lance les tests, construit, compile l'installateur (Inno Setup installé via choco), calcule le SHA-256 et crée la release, avec en notes la section du CHANGELOG. `tools/build.py` permet de faire la même chose en local.
- **Pré-requis sur le poste de Jean**, à installer avec son accord le moment venu :
  - Inno Setup 6 (`winget install JRSoftware.InnoSetup`), absent actuellement ;
  - un environnement virtuel `.venv` avec PySide6 épinglé en 6.11.1, sans toucher au Python global ;
  - `gh` (GitHub CLI) facultatif.
- **Signature de code** : l'exe n'est pas signé, SmartScreen affichera donc un avertissement. C'est à mentionner dans le README.

## 11. Récapitulatif des défauts à corriger

Il est repris aux sections 7.1 à 7.4. On y ajoute les points transverses :
- chaque outil avait son propre thème, sa gestion de `_MEIPASS`, ses réglages et ses scripts d'icône et de build : tout cela est mutualisé ;
- aucune police ni feuille de style n'est globale à un module ;
- `closeEvent` attend proprement tous les workers ;
- toute exception non gérée est journalisée et affichée dans un dialogue, sans quitter l'application en mode installé.

## 12. Tests et vérification

- **pytest**, avec l'interface testée hors écran (`QT_QPA_PLATFORM=offscreen`, `WA_DontShowOnScreen`, `grab()`).
- Tests à porter :
  - ceux de Compare ;
  - les scripts de Log Reader, convertis en pytest.
- Tests à écrire :
  - Link Checker (résolution, suggestions, corrections tout ou rien avec rollback), sur un petit projet synthétique versionné ;
  - Auto Validate : logique de décision et temporisations, avec les appels Win32 simulés ;
  - réglages : schéma, migration, écriture atomique ;
  - traduction : couverture FR, choix automatique de la langue selon Windows (fr-* → français, autre → anglais) ;
  - mises à jour : comparaison de versions et lecture de la réponse GitHub (HTTP simulé), vérification SHA-256 ;
  - instance unique et IPC.
- Le couple réel d'un client (données hors dépôt) reste ignoré s'il est absent, comme aujourd'hui.
- **Ressources**, à mesurer et à consigner dans le README à chaque phase :
  - mémoire du processus au repos (tray seul), puis avec chaque outil ouvert ;
  - CPU au repos (cible : environ 0 % hors événement) ;
  - taille de l'installateur ;
  - temps de démarrage.
- Pour vérifier l'exe : le lancer, puis `taskkill /IM OptixPlus.exe /F` si besoin.

## 13. Phases de livraison

À la fin de chaque phase : tests au vert, application lancée et vérifiée, commits faits. Je présente alors à Jean un court bilan (ce qui marche, ce qui a changé, les mesures) et j'attends son accord avant de passer à la suite si la phase touche l'interface.

0. **Socle** : venv, `pyproject`, `CLAUDE.md`, icône (`make_icon.py`), `common/` (chemins, réglages, thème violet, traduction, logging, workers, win32), instance unique et IPC, coquille (barre latérale, barre d'outils contextuelle, accueil, Journal, Paramètres Général), tray.
1. **Auto Validate** avec la surveillance par événements, branché sur le tray et l'accueil.
2. **Link Checker**.
3. **Compare**.
4. **Log Reader** avec onglets QtAds, multi-logs et restauration de session.
5. **Traduction française** complète et vérifiée ; bascule automatique selon la langue de Windows testée.
6. **Mises à jour, À propos, Nouveautés**.
7. **Construction, installateur, migration, workflow de publication.** Release `v1.0.0` publiée seulement avec l'accord de Jean.
8. *(Facultatif, après la 1.0.0)* **Lecture de projet Optix unifiée** pour Link Checker et Compare, dans `common/optix`, sans régression sur les tests.
9. **Mode découverte** distribué en exe portable.

## 14. Évolutivité : futurs modules

L'architecture doit permettre d'ajouter un outil sans toucher à la coquille :
- un nouvel outil = un paquet `modules/<id>/` (`core/` + `ui/` + `module.py`) et **une seule entrée** `ModuleSpec` dans `modules/__init__.py`. La barre latérale, le menu Outils, le menu du tray, la page d'accueil, les raccourcis et les Paramètres se construisent à partir de ce registre ;
- rien dans `shell/` ne doit connaître un outil par son nom (pas de `if module_id == "logreader"`). Les besoins communs passent par l'interface `ToolModule` et le contexte ;
- les briques partagées (lecture de projet Optix, sélection de projet et projets récents, sauvegarde/écriture sûre de YAML) sont pensées pour être réutilisées par les futurs outils ;
- les raccourcis Ctrl+1… suivent l'ordre du registre, et la barre latérale reste lisible au-delà de 4 outils (défilement si nécessaire).

**Module envisagé (à cadrer plus tard avec Jean)** : un outil d'aide aux **traductions dans FT Optix**. Il s'appuiera sur ce que Compare sait déjà lire (`Translations.yaml`, extracteur `translations.py`). Aucun développement tant qu'il n'a pas été spécifié.

## 15. Hors périmètre

- Comparaison automatique de logs.
- Signature de code.
- Toute modification des quatre dépôts sources.
