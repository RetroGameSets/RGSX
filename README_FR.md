# 🎮 Retro Game Sets Xtra (RGSX)

## SUPPORT / HELP : https://discord.gg/Vph9jwg3VV

RGSX est une application développée en Python basée sur Pygame pour la partie graphique pour la communauté par RetroGameSets. Elle est entièrement gratuite.

L'application prend en charge plusieurs sources comme myrient, 1fichier. Ces sources pourront être mises à jour fréquemment.

---

## 🧰 Utilisation en ligne de commande (CLI)

RGSX propose aussi une interface en ligne de commande (sans interface graphique) pour lister les plateformes/jeux et télécharger des ROMs :

- Guide FR: voir `https://github.com/RetroGameSets/RGSX/blob/main/README_CLI.md`

---

## ✨ Fonctionnalités

- **Téléchargement de jeux** : Prise en charge des fichiers ZIP et gestion des extensions non supportées à partir du fichier `es_systems.cfg` d'EmulationStation (et des `es_systems_*.cfg` personnalisés sur Batocera). RGSX lit les extensions autorisées par système depuis ces configurations et extrait automatiquement les archives si le système ne les supporte pas.
  - Les téléchargements ne nécessitent aucune authentification ni compte pour la plupart.
  - Les systèmes notés `(1fichier)` dans le nom ne seront accessibles que si vous renseignez votre clé API 1fichier (voir plus bas).
- **Historique des téléchargements** : Consultez et retéléchargez les anciens fichiers.
- **Téléchargements multi-sélection** : Marquez plusieurs jeux dans la liste avec la touche associée à Vider Historique (par défaut X) pour préparer un lot. Appuyez ensuite sur Confirmer pour lancer les téléchargements en séquence.
- **Personnalisation des contrôles** : Remappez les touches du clavier ou de la manette à votre convenance avec détection automatique des noms de boutons depuis EmulationStation(beta).
- **Grille des plateformes** : changez la disposition de la grille (3x3, 3x4, 4x3, 4x4) depuis le menu Affichage.
- **Afficher/Masquer plateformes non supportées** : masquage automatique des systèmes dont le dossier ROM est absent selon `es_systems.cfg`, avec un interrupteur dans le menu Affichage.
- **Images système plus intelligentes** : priorité à l’image explicite `platform_image` issue du JSON des systèmes avant les fallback `<platform_name>.png` ou dossier.
- **Changement de taille de police** : Si vous trouvez les écritures trop petites/trop grosses, vous pouvez le changer dans le menu.
- **Mode recherche** : Filtrez les jeux par nom pour une navigation rapide avec clavier virtuel sur manette.
- **Support multilingue** : Interface disponible en plusieurs langues. Vous pourrez choisir la langue dans le menu.
- **Gestion des erreurs** avec messages informatifs et fichier de LOG.
- **Interface adaptative** : L'interface s'adapte à toutes résolutions de 800x600 à 4K (non testé au-delà de 1920x1080).
- **Mise à jour automatique** : l'application doit être relancée après une mise à jour.
- **Cache des extensions supportées** : à la première utilisation, RGSX lit `es_systems.cfg` (RetroBat/Batocera) et génère `/saves/ports/rgsx/rom_extensions.json` avec les extensions autorisées par système.
- **Mise à jour automatique de la gamelist (Retrobat)** : sur Retrobat, le `gamelist.xml` Windows est mis à jour automatiquement au lancement pour afficher les images/vidéos dans EmulationStation.

---

## 🖥️ Prérequis

### Système d'exploitation
- Batocera / Knulli ou Retrobat

### Matériel
- PC, Raspberry, console portable...
- Manette (optionnelle, mais recommandée pour une expérience optimale) ou Clavier.
- Connexion internet active

### Espace disque
- 100 Mo pour l'application.

---

## 🚀 Installation

### Méthode 1 : Installation automatique en ligne de commande pour Batocera/Knulli

- Sur batocera x86 PC accéder à F1>Applications>xTERM ou
- Depuis un autre PC sur le réseau avec application Putty, powershell SSH ou autre

Entrez la commande :
## `curl -L bit.ly/rgsx-install | sh`
  
Patientez et regardez le retour à l'écran ou sur la commande (à améliorer).  
Mettez à jour la liste des jeux via : `Menu > Paramètres de jeux > Mettre à jour la liste des jeux`.  
Vous trouverez RGSX dans le système "PORTS" ou "Jeux Amateurs et portages" et dans `/roms/ports/RGSX`

---

### Méthode 2 : Copie manuelle (Méthode obligatoire sur retrobat)

- Téléchargez le contenu du dépôt en zip : https://github.com/RetroGameSets/RGSX/archive/refs/heads/main.zip
- Extrayez le fichier zip dans le dossier ROMS (pour Batocera, seul le dossier PORTS sera utilisé pour Retrobat il faudra extraire PORTS et WINDOWS)
- Mettez à jour la liste des jeux via le menu :  
  `Paramètres de jeux > Mettre à jour la liste`.

## 🏁 Premier démarrage
---
> ## IMPORTANT
> Si vous avez une clé API 1Fichier, vous devez la renseigner dans  
> `/saves/ports/rgsx/1FichierAPI.txt`  
> si vous souhaitez télécharger depuis des liens 1Fichier.
---

- Lancez RGSX depuis ports sur batocera, depuis Windows sur Retrobat.
- Au premier lancement, l'application importera automatiquement la configuration des contrôles depuis EmulationStation si disponible.
- Configurez les contrôles si nécessaire. Ils pourront être reconfigurés via le menu pause par la suite.
- Supprimez le fichier `/saves/ports/rgsx/controls.json` en cas de problème puis relancez l'application.
- L'application téléchargera toutes les données nécessaires automatiquement ensuite.

INFO : pour retrobat au premier lancement, l'application téléchargera Python dans le dossier /system/tools/python qui est nécessaire pour faire fonctionner l'application. Le fichier fait environ 50 Mo et va assez vite à télécharger mais il n'y a aucun retour visuel à l'écran, qui va rester figé sur le chargement de RGSX pendant quelques secondes.
---

## 🕹️ Utilisation

### Navigation dans les menus

- Utilisez les touches directionnelles (D-Pad, flèches du clavier) pour naviguer entre les plateformes, jeux et options.
- Appuyez sur la touche configurée comme start (par défaut, **P** ou bouton Start sur la manette) pour ouvrir le menu pause.
- Depuis le menu pause, accédez à l'historique, à l'aide des contrôles (l'affichage des contrôles change suivant le menu où vous êtes) ou à la reconfiguration des touches, des langues, de la taille de la police.
- Vous pouvez aussi, depuis le menu, régénérer le cache de la liste des systèmes/jeux/images pour être sûr d'avoir les dernières mises à jour.

#### Menu Affichage

- Disposition: basculez la grille des plateformes entre 3x3, 3x4, 4x3, 4x4.
- Taille de police: ajustez l’échelle du texte (accessibilité).
- Afficher plateformes non supportées: afficher/masquer les systèmes dont le dossier ROM est absent.
- Filtrer les systèmes: afficher/masquer rapidement des plateformes par nom (persistant).

---

### Téléchargement

- Sélectionnez une plateforme, puis un jeu.
- Appuyez sur la touche configurée confirm (par défaut, **Entrée** ou bouton **A**) pour lancer le téléchargement.
- Option : appuyez sur la touche Vider Historique (par défaut **X**) sur plusieurs jeux pour activer/désactiver leur sélection (marqueur [X]). Puis validez pour lancer un lot de téléchargements.
- Suivez la progression dans le menu `HISTORIQUE`.

---

### Personnalisation des contrôles

- Dans le menu pause, sélectionnez **Reconfigurer controls**.
- Suivez les instructions à l'écran pour mapper chaque action en maintenant la touche ou le bouton pendant 3 secondes.
- Les noms des boutons s'affichent automatiquement selon votre manette (A, B, X, Y, LB, RB, LT, RT, etc.).
- La configuration est compatible avec toutes les manettes supportées par EmulationStation.
- En cas de problème de contrôles ou configuration corrompue, supprimez le fichier : `/saves/ports/rgsx/controls.json` puis redémarrez l'application (il sera recréé automatiquement).

---

### Historique

- Accédez à l'historique des téléchargements via le menu pause ou en appuyant sur la touche historique (par défaut, **H**).
- Sélectionnez un jeu pour le retélécharger si nécessaire en cas d'erreur ou annulation.
- Videz tout l'historique via le bouton **EFFACER** dans le menu historique. Les jeux ne sont pas effacés seulement la liste.
- Annulez un téléchargement avec le bouton **RETOUR**

---

### Logs

Les logs sont enregistrés dans `roms/ports/RGSX/logs/RGSX.log` sur batocera et sur Retrobat pour diagnostiquer les problèmes et seront à partager pour tout support.

---

## 🔄 Journal des modifications

### 2.1.0.0 (2025-09-09)
- Retrobat : mise à jour automatique de `gamelist.xml` au lancement pour afficher immédiatement les images/vidéos dans ES.
- Chargement des images systèmes : priorité à `platform_image` défini dans le JSON des systèmes.
- Détection automatique des extensions supportées via `es_systems.cfg`; génération et cache dans `/saves/ports/rgsx/rom_extensions.json`.
- Masquage automatique des plateformes non supportées (dossier ROM manquant selon `es_systems.cfg`) avec interrupteur dans le menu Affichage.
- Nouveau réglage dans Affichage pour changer la grille des plateformes (3x3, 3x4, 4x3, 4x4).
- Réorganisation du menu pause pour mettre en avant les options courantes.
- Traductions mises à jour.
- Corrections visuelles mineures et ajustements d’espacements.

### 2.0.0.0 (2025-09-05)
- Refonte complète du système de sources : gestion centralisée via `/saves/ports/rgsx/systems_list.json` (ordre conservé), ajout automatique d’une plateforme en déposant son fichier JSON dans `/saves/ports/rgsx/games/` (création si absente) — pensez ensuite à éditer le champ "dossier" généré pour qu’il corresponde à votre organisation de téléchargements.
- Nouveau menu de filtrage des systèmes (afficher/masquer plateformes avec persistance dans les paramètres)
- En-tête de la liste des jeux (Nom / Taille) traduit
- Détection automatique de l'ancien fichier sources.json → purge sécurisée du cache + popup de redémarrage (aucune migration)
- Fiabilité améliorée des téléchargements Archive.org : stratégie de retry multi-entêtes + préchargement métadonnées
- Synchronisation des traductions (FR/EN/ES/DE/PT) et complétion des clés manquantes
- Refactors internes : early-return unifié dans load_sources, reconstruction de cache plus sûre

### 1.9.9.4 (2025-09-03)
- Bascule Source des jeux (RGSX / Personnalisée) + popups
- Pas de fallback si source personnalisée invalide (liste vide + message)
- Réorganisation menu pause (Source avant Mise à jour)
- Messages d’état symlink + traductions mineures
- Correction minuterie popup et placeholders de chemin

### 1.9.9.3
- Ajout option symlink (dossiers plateformes imbriqués)
- Persistance et traductions symlink

### 1.9.9.2
- Fichier unifié rgsx_settings.json (langue, musique, accessibilité, symlink, sources)
- Migration automatique anciens JSON

### 1.9.9.1
- Téléchargements multi-sélection & historique amélioré
- Gestion archives + meilleures popups d’erreur

### 1.9.9.0
- Taille de police (accessibilité), sélection langue, aide contrôles, système de mise à jour

### 1.9.8.x
- Fonctionnalités initiales publiques (téléchargements, remapping manette, interface adaptative, logs)

---

## 🌐 Sources de jeux personnalisées
Vous pouvez changer la source dans le menu pause (Source des jeux : RGSX / Personnalisée).

Le mode personnalisé attend une URL ZIP (HTTP/HTTPS) pointant vers une archive des sources avec la même structure que celle par défaut. À configurer dans :
`{chemin rgsx_settings}` → clé : `sources.custom_url`

Comportement :
- Si mode personnalisé sélectionné et URL vide/invalide → liste vide + popup (aucun fallback)
- Corrigez l’URL puis utilisez "Mettre à jour la liste des jeux" et redémarrez si nécessaire

Exemple dans rgsx_settings.json :
```json
"sources": {
  "mode": "custom",
  "custom_url": "https://exemple.com/mes-sources.zip"
}
```
Revenez au mode RGSX à tout moment via le menu pause.

---

## 📁 Structure du projet
```
/roms/windows/RGSX
│
├── RGSX Retrobat.bat    # Raccourci pour lancer l'application RGSX pour retrobat uniquement, non nécessaire pour batocera/knulli

/roms/ports/
RGSX-INSTALL.log         # LOG d'installation uniquement pour une première installation en ligne de commande.
RGSX/
│
├── __main__.py          # Point d'entrée principal de l'application.
├── controls.py          # Gestion des événements clavier/manette/souris et navigation dans les menus.
├── controls_mapper.py   # Configuration des contrôles avec détection automatique des noms de boutons.
├── display.py           # Rendu des interfaces graphiques avec Pygame.
├── config.py            # Configuration globale (chemins, paramètres, etc.).
├── rgsx_settings.py     # Gestion unifiée des paramètres de l'application.
├── network.py           # Gestion des téléchargements de jeux.
├── history.py           # Gestion de l'historique des téléchargements.
├── language.py          # Gestion du support multilingue.
├── accessibility.py     # Gestion des paramètres d'accessibilité.
├── utils.py             # Fonctions utilitaires (wrap du texte, troncage etc.).
├── update_gamelist.py   # Mise à jour de la liste des jeux (Batocera/Knulli).
├── update_gamelist_windows.py  # Spécifique Retrobat : mise à jour auto de gamelist.xml au lancement.
├── assets/              # Ressources de l'application (polices, exécutables, musique).

├── languages/           # Fichiers de traduction.
└── logs/
    └── RGSX.log         # Fichier de logs.

/saves/ports/RGSX/
│
├── systems_list.json    # Liste des systèmes 
├── games/               # Liens des systèmes
├── images/              # Images des systèmes.
├── rgsx_settings.json   # Fichier de configuration unifié (paramètres, accessibilité, langue, musique, symlinks).
├── controls.json        # Fichier de mappage des contrôles (généré après le premier démarrage).
├── history.json         # Base de données de l'historique de téléchargements (généré après le premier téléchargement).
├── rom_extensions.json  # Généré depuis es_systems.cfg : cache des extensions autorisées par système.
└── 1FichierAPI.txt      # Clé API 1fichier (compte premium et + uniquement) (vide par défaut).
```

---

## 🤝 Contribution

### Signaler un bug

1. Consultez les logs dans `/roms/ports/RGSX/logs/RGSX.log`.
2. Ouvrez une issue sur GitHub avec une description détaillée et les logs pertinents.

### Proposer une fonctionnalité

- Soumettez une issue avec une description claire de la fonctionnalité proposée.
- Expliquez comment elle s'intègre dans l'application.

### Contribuer au code

1. Forkez le dépôt et créez une branche pour votre fonctionnalité ou correction :
```bash
git checkout -b feature/nom-de-votre-fonctionnalité
```
2. Testez vos modifications sur Batocera.
3. Soumettez une pull request avec une description détaillée.

---

## ⚠️ Problèmes connus / À implémenter

- (Aucun listé actuellement)

---

## 📝 Licence

Ce projet est libre. Vous êtes libre de l'utiliser, le modifier et le distribuer selon les termes de cette licence.

Développé avec ❤️ pour les amateurs de jeux rétro.
