# Nouveautés

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; les versions suivent le [versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
- Version portable : `OptixPlus-Portable-X.Y.Z.exe`, un seul fichier à lancer sans installation. Elle fonctionne en mode découverte : pas d'icône dans la zone de notification, rien d'écrit dans le registre, et la surveillance de FT Optix Studio s'arrête à la fermeture de la fenêtre. Les réglages sont les mêmes que ceux de la version installée.
- L'À propos et la page Validation auto indiquent le mode découverte.
- OptixPlus lancé en administrateur : un appui sur Impr. écran seule (sans Alt, Ctrl, Maj ni Windows, qui fonctionnent) dans une de ses fenêtres affiche un message qui explique pourquoi la capture n'a pas lieu (Windows bloque les logiciels de capture lancés normalement) et comment faire ; « Ne plus afficher ce message » est mémorisé.

### Modifié
- Menu de l'icône de la zone de notification allégé : Ouvrir OptixPlus, Surveillance active, Rechercher les mises à jour, À propos, Quitter. Les outils et les paramètres s'ouvrent depuis la fenêtre.
- Page Validation auto : les boutons en doublon de la barre d'outils sont retirés (Suspendre la surveillance, Effacer, Ouvrir le fichier journal) ; « Ouvrir le dossier du journal » passe dans la barre d'outils.
- Réglages de la Validation auto déplacés dans la fenêtre Paramètres (catégorie « Validation auto »), appliqués par OK ou Appliquer ; la page de l'outil garde l'état et le journal, et sa barre d'outils ouvre ces réglages (« Paramètres de la surveillance… »).
- Contrôle des liens : la progression de l'analyse et le bouton Annuler s'affichent sur la ligne « Afficher », à la place de la synthèse ; le tableau des résultats ne change plus de taille à chaque analyse.
- Fermer la fenêtre de la version installée : si la surveillance de FT Optix Studio est active, OptixPlus reste dans la zone de notification et le signale par une bulle ; si elle est suspendue, OptixPlus se ferme complètement.
- Installation dans `C:\Program Files\OptixPlus`, comme un logiciel classique, pour tous les utilisateurs du poste (une confirmation administrateur est demandée, y compris pour les mises à jour). Une version 1.0.0 installée dans le profil est remplacée, réglages conservés.

### Corrigé
- Lecteur de logs : la pastille de l'onglet suit l'état de la connexion (elle restait verte après une perte de connexion). Le voyant de la barre du bas, devenu inutile, est retiré, et cette barre prend le fond de la page.
- Changement de thème : une erreur interrompait la recoloration des icônes (barres d'outils des outils comprises).
- Raccourcis des outils (F5 : Analyser…) actifs dès l'affichage de l'outil : il fallait auparavant cliquer d'abord dans sa page. À l'ouverture d'un outil, le focus clavier passe dans sa page.
- OptixPlus n'est plus lancé avec les droits administrateur par l'installateur (case « Lancer OptixPlus », relance après mise à jour) : une fenêtre élevée empêchait les logiciels de capture d'écran (Greenshot…) de recevoir leurs raccourcis. Lancé volontairement en administrateur, il le reste.
- Recherche de mise à jour : la connexion sécurisée à GitHub est vérifiée par Windows, ce qui corrige l'erreur « CERTIFICATE_VERIFY_FAILED » sur les postes où le certificat racine n'était pas encore installé ou derrière un antivirus ou un proxy qui inspecte le HTTPS.
- La page Validation auto ne reste plus abonnée au service de surveillance après sa fermeture (changement de langue, fenêtre refermée).

## [1.0.0] - 2026-09-23

### Ajouté
- Socle de l'application : fenêtre principale avec barre latérale, page d'accueil, journal intégré, paramètres, « À propos ».
- Icône OptixPlus : le disque de FT Optix Studio en violet, trou rond centré, « + » détouré de blanc posé sur le bord du trou.
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
- Les barres de filtres et de période passent à la ligne et la barre d'état s'abrège quand la place manque : deux journaux tiennent côte à côte.

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
