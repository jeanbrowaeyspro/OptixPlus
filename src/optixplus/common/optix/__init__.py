"""Lecture de projets FactoryTalk Optix, commune aux outils (Link Checker, Compare…).

- ``text`` : fichiers texte lus à l'octet près (BOM, fins de ligne), sans décodage ;
- ``project`` : reconnaissance d'un dossier projet, fichier ``.optix``, références ``- File:`` ;
- ``scanner`` : index des nœuds d'un fichier YAML Optix par une passe ligne à ligne ;
- ``tree`` : arbre des nœuds de tout le projet, en suivant les inclusions.
"""
