# 🎮 Retro Game Sets Xtra (RGSX)

## SUPPORT / HELP : https://discord.gg/Vph9jwg3VV

RGSX est une application développée en Python basée sur Pygame pour la partie graphique pour la communauté par RetroGameSets. Elle est entièrement gratuite.

L'application prend en charge plusieurs sources comme myrient, 1fichier. Ces sources pourront être mises à jour fréquemment.

---

## ✨ Fonctionnalités

- **Téléchargement de jeux** : Prise en charge des fichiers ZIP et gestion des extensions non supportées grâce au fichier `info.txt` dans chaque dossier (batocera), qui extrait automatiquement si le système ne supporte pas les archives.
  - Les téléchargements ne nécessitent aucune authentification ni compte pour la plupart.
  - Les systèmes notés `(1fichier)` dans le nom ne seront accessibles que si vous renseignez votre clé API 1fichier (voir plus bas).
- **Historique des téléchargements** : Consultez et retéléchargez les anciens fichiers.
- **Téléchargements multi-sélection** : Marquez plusieurs jeux dans la liste avec la touche associée à Vider Historique (par défaut X) pour préparer un lot. Appuyez ensuite sur Confirmer pour lancer les téléchargements en séquence.
- **Personnalisation des contrôles** : Remappez les touches du clavier ou de la manette à votre convenance avec détection automatique des noms de boutons depuis EmulationStation(beta).
- **Changement de taille de police** : Si vous trouvez les écritures trop petites/trop grosses, vous pouvez le changer dans le menu.
- **Mode recherche** : Filtrez les jeux par nom pour une navigation rapide avec clavier virtuel sur manette.
- **Support multilingue** : Interface disponible en plusieurs langues. Vous pourrez choisir la langue dans le menu.
- **Gestion des erreurs** avec messages informatifs et fichier de LOG.
- **Interface adaptative** : L'interface s'adapte à toutes résolutions de 800x600 à 4K (non testé au-delà de 1920x1080).
- **Mise à jour automatique** : l'application doit être relancée après une mise à jour.

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
├── es_input_parser.py   # Parseur de configuration EmulationStation pour l'import automatique des contrôles.
├── display.py           # Rendu des interfaces graphiques avec Pygame.
├── config.py            # Configuration globale (chemins, paramètres, etc.).
├── rgsx_settings.py     # Gestion unifiée des paramètres de l'application.
├── network.py           # Gestion des téléchargements de jeux.
├── history.py           # Gestion de l'historique des téléchargements.
├── language.py          # Gestion du support multilingue.
├── accessibility.py     # Gestion des paramètres d'accessibilité.
├── utils.py             # Fonctions utilitaires (wrap du texte, troncage etc.).
├── update_gamelist.py   # Mise à jour de la liste des jeux.
├── assets/              # Ressources de l'application (polices, exécutables, musique).
├── games/               # Fichiers de configuration des systèmes de jeux.
├── images/              # Images des systèmes.
├── languages/           # Fichiers de traduction.
└── logs/
    └── RGSX.log         # Fichier de logs.

/saves/ports/RGSX/
│
├── rgsx_settings.json   # Fichier de configuration unifié (paramètres, accessibilité, langue, musique, symlinks).
├── controls.json        # Fichier de mappage des contrôles (généré après le premier démarrage).
├── history.json         # Base de données de l'historique de téléchargements (généré après le premier téléchargement).
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
