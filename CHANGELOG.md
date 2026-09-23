# Nouveautés

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; les versions suivent le [versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
- Socle de l'application : fenêtre principale avec barre latérale, page d'accueil, journal intégré, paramètres, « À propos ».
- Icône OptixPlus (anneau violet et « + »).
- Instance unique : un second lancement ramène la fenêtre existante.
- Icône dans la zone de notification en mode installé.
- Interface bilingue français / anglais, qui suit la langue de Windows ; chaque texte affiché est vérifié dans les deux langues. La ligne de commande suit la même langue que la fenêtre.
- Thèmes Système, Clair et Sombre.
- Mises à jour par les Releases GitHub : recherche automatique (au démarrage, tous les jours ou toutes les semaines) ou à la demande depuis le menu Aide, le tray et les Paramètres ; préversions en option.
  - Notes de version affichées avant de choisir : Installer maintenant, Plus tard ou Ignorer cette version.
  - Installateur téléchargé puis vérifié par son empreinte SHA-256 avant tout lancement.
- Fenêtre Nouveautés au premier lancement d'une nouvelle version, et à tout moment depuis le menu Aide.
- Installateur Windows : installation sans droits administrateur, français ou anglais selon Windows, démarrage avec Windows au choix, désinstallation qui demande avant d'effacer les réglages.
- Reprise des anciens outils proposée à l'installation (décochée) : réglages de Log Reader, Link Checker, Compare et Auto Validate, retrait du démarrage automatique de l'ancien OptixAutoValidate. Rien n'est supprimé des anciens outils, et aucun réglage d'OptixPlus n'est écrasé.
- Outil **Validation auto** (ex-OptixAutoValidate) : validation automatique de la boîte « Le projet existe déjà » de FT Optix Studio.
  - Détection par événements Windows au lieu d'un balayage des fenêtres toutes les 150 ms : consommation quasi nulle au repos.
  - Réglages et journal de la surveillance réunis sur une seule page ; carte sur l'accueil ; état dans la barre d'état et l'infobulle du tray.
  - Icône du tray grisée quand la surveillance est suspendue.
- Outil **Contrôle des liens** (ex-Optix LinkCheck) : détection et réparation des DynamicLink cassés d'un projet FT Optix.
  - Analyse et corrections en arrière-plan, analyse annulable, progression sur les fichiers réellement inclus.
  - Projets récents partagés, affichés sur l'accueil (un clic ouvre le projet).
  - Statistiques complètes, y compris les liens vers les objets internes ; avertissement si FT Optix Studio est ouvert avant d'écrire.
  - Mode ligne de commande conservé : `optixplus linkcheck <dossier> [--fix-prefix]`.
- Outil **Comparaison** (ex-FTOCompare) : comparaison runtime ⇄ projet, plan de décision, application sécurisée.
  - Interface et rapports Markdown / HTML bilingues ; menus de FTOCompare réunis dans la barre d'actions de l'outil.
  - Historique des couples, arbitrages mémorisés et dernier export rangés dans les réglages d'OptixPlus.
  - Le projet comparé rejoint les projets récents ; un projet récent s'ouvre aussi dans Comparaison.
- Outil **Lecteur de logs** (ex-pyFTOLogReader) : suivi en direct du journal runtime des automates FT Optix.
  - Plusieurs journaux ouverts en onglets, à la façon de Visual Studio : onglets côte à côte (gauche/droite, haut/bas) par glisser-déposer, ou sortis dans des fenêtres flottantes.
  - Chaque onglet porte un voyant de connexion et le nombre d'erreurs arrivées pendant qu'il était caché.
  - Les onglets ouverts et leur disposition sont rouverts à la prochaine ouverture (réglable).
  - Automates récents sur l'accueil (un clic ouvre leur journal) ; « Ouvrir un journal… » dans le menu du tray.
  - Réglages rangés dans les paramètres d'OptixPlus, mots de passe toujours chiffrés par la DPAPI Windows.

### Corrigé (par rapport à l'ancien pyFTOLogReader)
- Un partage réseau qui ne répond plus n'oblige plus à tuer le fil de lecture : la lecture bloquée est annulée proprement, et la fermeture ne provoque plus de plantage.
- Le suivi dort vraiment entre deux relectures au lieu de se réveiller en boucle.
- Environ un tiers de mémoire en moins par ligne : la ligne brute est reconstruite à la demande.
- Compteurs d'erreurs et d'avertissements tenus à jour au fil de l'eau, sans recompter tout le journal.
- Réglages validés au chargement : une valeur invalide revient au défaut au lieu de bloquer le démarrage.
- La barre de filtres passe sur deux lignes et la barre d'état s'abrège quand la place manque : deux journaux tiennent côte à côte.

### Corrigé (par rapport à l'ancien FTOCompare)
- La prévisualisation du plan est calculée en arrière-plan : l'interface ne se fige plus sur un gros projet.
- La vue diff construit ses lignes à la demande : quelques centaines d'entrées au lieu d'un objet par ligne.
- Recherche d'un fichier de l'inventaire par index, au lieu d'un parcours complet à chaque appel.
- Le jargon « hunk » est remplacé par « différence » dans l'interface et les messages.
- Couleurs issues du thème (lisibles en sombre) ; libellés définis une seule fois pour l'interface et les rapports.
- La fermeture de la boîte d'application attend la fin d'une restauration en cours, sans délai arbitraire.

### Corrigé (par rapport à l'ancien Optix LinkCheck)
- Analyse environ quatre fois plus rapide sur un gros projet (17,7 s → 4,2 s sur un projet de 1,1 million de lignes) : les YAML générés par FT Optix sont lus directement, PyYAML ne servant plus qu'aux fichiers au format inhabituel. Résultats identiques, vérifiés nœud par nœud.
- Les corrections sont appliquées en tout ou rien : en cas d'échec, les fichiers déjà écrits sont restaurés.
- Le remplacement d'une cible porte sur la valeur exacte de la ligne, et non sur la première occurrence du texte.
- Les projets très profonds ne font plus planter la lecture (construction de l'arbre sans récursion).
- Un projet dont le nom est contenu dans un autre (« IHM » et « IHM_Ligne2 ») n'est plus confondu.

### Corrigé (par rapport à l'ancien OptixAutoValidate)
- La mise au premier plan de secours n'active plus la barre de menus de l'application en cours d'utilisation.
- Le focus n'est rendu à la fenêtre précédente que si l'utilisateur n'est pas passé à autre chose entre-temps.
