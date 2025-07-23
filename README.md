# 🎮 Retro Game Sets Xtra (RGSX)

RGSX est une application Python basée sur Pygame.

---

## ✨ Fonctionnalités

- **Téléchargement de jeux** : Prise en charge des fichiers ZIP et gestion des extensions non supportées grâce au fichier `info.txt` dans chaque dossier.
  - Les téléchargements ne nécessitent aucune authentification ni compte pour la plupart.
  - Les systèmes notés `(1fichier)` dans le nom ne seront accessibles que si vous renseignez votre clé API 1fichier (voir plus bas).
- **Historique des téléchargements** : Consultez et retéléchargez les anciens fichiers.
- **Personnalisation des contrôles** : Remappez les touches du clavier ou de la manette à votre convenance.
- **Mode recherche** : Filtrez les jeux par nom pour une navigation rapide.
- **Gestion des erreurs**
- **Interface réactive** : L'interface s'adapte à toutes résolutions de 800x600 à 4K (non testé au-delà de 1920x1080).
- **Mise à jour automatique** (bug d'affichage à améliorer lors d'une mise à jour) : l'application doit être relancée après sa fermeture automatique.

---

## 🖥️ Prérequis

### Système d'exploitation
- Batocera ou Knulli

### Matériel
- Manette (optionnelle, mais recommandée pour une expérience optimale) ou Clavier.

### Espace disque
- Espace suffisant dans `/userdata/roms/ports/RGSX` pour stocker les ROMs, images et fichiers de configuration.

---

## 🚀 Installation

### Méthode 1 : Ligne de commande

- Sur batocera PC acceder à F1>Applications>xTERM  ou
- Depuis un autre pc sur le réseau avec application Putty, powershell SSH ou autre

Entrez la commande :
## `curl -L bit.ly/rgsx-install | sh`
  
Patientez et regardez le retour à l'écran ou sur la commande (à améliorer).  
Mettez à jour la liste des jeux via : `Menu > Paramètres de jeux > Mettre à jour la liste des jeux `.  
Vous trouverez RGSX dans le système "PORTS" ou "Jeux Amateurs et portages" et dans `/userdata/roms/ports/RGSX`

---

### Méthode 2 : Copie manuelle

- Téléchargez le contenu du dépôt en zip : https://github.com/RetroGameSets/RGSX/archive/refs/heads/main.zip
- Extrayez le tout dans `/userdata/roms/ports/RGSX` (le dossier RGSX devra être créé manuellement). Attention de bien respecter la structure indiquée plus bas.
- Mettez à jour la liste des jeux via le menu :  
  `Paramètres de jeux > Mettre à jour la liste`.


## 🏁 1er démarrage
---
> ## IMPORTANT
> Si vous avez une clé API 1Fichier, vous devez la renseigner dans  
> `/userdata/saves/ports/RGSX/1FichierAPI.txt`  
> si vous souhaitez télécharger depuis des liens 1Fichier.
---

- Lancez RGSX depuis ports.
- Configurez les contrôles. Ils pourront être reconfigurés via le menu pause par la suite si erreur.
- Supprimez le fichier `/userdata/saves/ports/rgsx/controls.json` en cas de problème puis relancez l'application.
- L'application téléchargera toutes les données nécessaires automatiquement ensuite.

---

## 🕹️ Utilisation

### Navigation dans les menus

- Utilisez les touches directionnelles (D-Pad, flèches du clavier) pour naviguer entre les plateformes, jeux et options.
- Appuyez sur la touche configurée comme start (par défaut, **P** ou bouton Start sur la manette) pour ouvrir le menu pause.
- Depuis le menu pause, accédez à l'historique, à l'aide des contrôles (l'affichage des contrôles change suivant le menu où vous êtes) ou à la reconfiguration des touches.
- Vous pouvez aussi, depuis le menu, régénérer la liste des systèmes/jeux/images pour être sûr d'avoir les dernières mises à jour.

---

### Téléchargement

- Sélectionnez une plateforme, puis un jeu.
- Appuyez sur la touche configurée confirm (par défaut, **Entrée** ou bouton **A**) pour lancer le téléchargement.
- Suivez la progression dans le menu `download_progress`.

---

### Personnalisation des contrôles

- Dans le menu pause, sélectionnez **Remap controls**.
- Suivez les instructions à l'écran pour mapper chaque action en maintenant la touche ou le bouton pendant 3 secondes.
- Appuyez sur **Échap** pour ignorer une action sans la mapper.

---

### Historique

- Accédez à l'historique des téléchargements via le menu pause ou en appuyant sur la touche history (par défaut, **H**).
- Sélectionnez un jeu pour le retélécharger si nécessaire.

---

### Logs

Les logs sont enregistrés dans `/userdata/roms/ports/RGSX/logs/RGSX.log` pour diagnostiquer les problèmes.

---

## 📁 Structure du projet
```
/userdata/roms/ports/
RGSX-INSTALL.log         # LOG d'installation uniquement
RGSX/
│
├── main.py              # Point d'entrée principal de l'application.
├── controls.py          # Gestion des événements clavier/manette/souris et navigation dans les menus.
├── controls_mapper.py   # Configuration des contrôles.
├── display.py           # Rendu des interfaces graphiques avec Pygame.
├── config.py            # Configuration globale (chemins, paramètres, etc.).
├── network.py           # Gestion des téléchargements de jeux.
├── history.py           # Gestion de l'historique des téléchargements.
├── utils.py             # Fonctions utilitaires (wrap du texte, troncage etc.).
└── logs/
    └── RGSX.log         # Fichier de logs.

/userdata/saves/ports/
RGSX/
│
├── controls.json        # Fichier de mappage des contrôles  (généré après le 1er demarrage)
├── history.json         # Base de données de l'historique de téléchargements (généré après le 1er téléchargement)
└── 1FichierAPI.txt      # Clé API 1fichier (compte premium et + uniquement) (vide par defaut)
```





---

## 🤝 Contribution

### Signaler un bug

1. Consultez les logs dans `/userdata/roms/ports/RGSX/logs/RGSX.log`.
2. Ouvrez une issue sur GitHub avec une description détaillée et les logs pertinents.

### Proposer une fonctionnalité

- Soumettez une issue avec une description claire de la fonctionnalité proposée.
- Expliquez comment elle s'intègre dans l'application.

### Contribuer au code

1. Forkez le dépôt et créez une branche pour votre fonctionnalité ou correction :
git checkout -b feature/nom-de-votre-fonctionnalité
2. Testez vos modifications sur Batocera.
3. Soumettez une pull request avec une description détaillée.

---

## ⚠️ Problèmes connus / À implémenter

- Gestion des téléchargements multiples

---

## 📝 Licence

Ce projet est libre. Vous êtes libre de l'utiliser, le modifier et le distribuer selon les termes de cette licence.

Développé avec ❤️ pour les amateurs de jeux rétro.
