# Nouveautés

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; les versions suivent le [versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
- Socle de l'application : fenêtre principale avec barre latérale, page d'accueil, journal intégré, paramètres, « À propos ».
- Icône OptixPlus (anneau violet et « + »).
- Instance unique : un second lancement ramène la fenêtre existante.
- Icône dans la zone de notification en mode installé.
- Interface bilingue français / anglais, qui suit la langue de Windows.
- Thèmes Système, Clair et Sombre.
- Outil **Validation auto** (ex-OptixAutoValidate) : validation automatique de la boîte « Le projet existe déjà » de FT Optix Studio.
  - Détection par événements Windows au lieu d'un balayage des fenêtres toutes les 150 ms : consommation quasi nulle au repos.
  - Réglages et journal de la surveillance réunis sur une seule page ; carte sur l'accueil ; état dans la barre d'état et l'infobulle du tray.
  - Icône du tray grisée quand la surveillance est suspendue.
- Outil **Contrôle des liens** (ex-Optix LinkCheck) : détection et réparation des DynamicLink cassés d'un projet FT Optix.
  - Analyse et corrections en arrière-plan, analyse annulable, progression sur les fichiers réellement inclus.
  - Projets récents partagés, affichés sur l'accueil (un clic ouvre le projet).
  - Statistiques complètes, y compris les liens vers les objets internes ; avertissement si FT Optix Studio est ouvert avant d'écrire.
  - Mode ligne de commande conservé : `optixplus linkcheck <dossier> [--fix-prefix]`.

### Corrigé (par rapport à l'ancien Optix LinkCheck)
- Les corrections sont appliquées en tout ou rien : en cas d'échec, les fichiers déjà écrits sont restaurés.
- Le remplacement d'une cible porte sur la valeur exacte de la ligne, et non sur la première occurrence du texte.
- Les projets très profonds ne font plus planter la lecture (construction de l'arbre sans récursion).
- Un projet dont le nom est contenu dans un autre (« IHM » et « IHM_Ligne2 ») n'est plus confondu.

### Corrigé (par rapport à l'ancien OptixAutoValidate)
- La mise au premier plan de secours n'active plus la barre de menus de l'application en cours d'utilisation.
- Le focus n'est rendu à la fenêtre précédente que si l'utilisateur n'est pas passé à autre chose entre-temps.
