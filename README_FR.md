# 🎮 Retro Game Sets Xtra (RGSX)

## SUPPORT / HELP : https://discord.gg/Vph9jwg3VV

RGSX est une application développée en Python basée sur Pygame pour la partie graphique pour la communauté par RetroGameSets. Elle est entièrement gratuite.

L'application prend en charge plusieurs sources comme myrient, 1fichier (avec support de débridage via AllDebrid en option). Ces sources pourront être mises à jour fréquemment.



## ✨ Fonctionnalités

- **Téléchargement de jeux** : Prise en charge des fichiers ZIP et gestion des extensions non supportées à partir du fichier `es_systems.cfg` d'EmulationStation (et des `es_systems_*.cfg` personnalisés sur Batocera). RGSX lit les extensions autorisées par système depuis ces configurations et extrait automatiquement les archives si le système ne les supporte pas.
  - Les téléchargements ne nécessitent aucune authentification ni compte pour la plupart.
  - Les systèmes notés `(1fichier)` dans le nom ne seront accessibles que si vous renseignez votre clé API (1Fichier,AllDebrid, Real-Debrid)
---
> ## IMPORTANT (1Fichier / AllDebrid / Real-Debdrid)
> Pour télécharger depuis des liens 1Fichier, vous pouvez utiliser soit votre clé API 1Fichier, soit votre clé API AllDebrid (fallback automatique si 1Fichier est absent).
>
> Où coller votre clé API (le fichier doit contenir uniquement la clé) :
> - `/saves/ports/rgsx/1FichierAPI.txt` (clé API 1Fichier)
> - `/saves/ports/rgsx/AllDebridAPI.txt` (clé API AllDebrid)
> - `/saves/ports/rgsx/RealDebridAPI.txt` (clé API Real-Debrid)
>
> Ne créez PAS ces fichiers manuellement. Lancez une première fois l'application RGSX : elle créera automatiquement les fichiers vides s’ils sont absents. Ensuite, ouvrez le fichier correspondant et collez votre clé.
---

**🧰 Utilisation en ligne de commande (CLI)**

RGSX propose aussi une interface en ligne de commande (sans interface graphique) pour lister les plateformes/jeux et télécharger des ROMs :

- Guide FR: voir `https://github.com/RetroGameSets/RGSX/blob/main/README_CLI.md`

- **Historique des téléchargements** : Consultez la liste de tous les téléchargements actuels et anciens.

- **Téléchargements multi-sélection** : Marquez plusieurs jeux dans la liste avec la touche associée à Vider Historique (par défaut X) pour préparer un lot. Appuyez ensuite sur Confirmer pour lancer les téléchargements en séquence.

- **Personnalisation des contrôles** : Remappez les touches du clavier ou de la manette à votre convenance, par defaut certaines manettes sont automatiquement configurées

- **Grille des plateformes** : Possibilité de modifier la disposition de la grille des plateformes (3x3, 3x4, 4x3, 4x4)

- **Afficher/Masquer plateformes non supportées** : masquage automatique des systèmes dont le dossier ROM est absent selon `es_systems.cfg`, avec un interrupteur dans le menu Affichage.

- **Changement de police et de taille** : Si vous trouvez les écritures trop petites/trop grosses, pas assez lisibles, vous pouvez le changer dans le menu.

- **Mode recherche / Filtre** : Filtrez les jeux par nom pour une navigation rapide avec clavier virtuel sur manette.

- **Support multilingue** : Interface disponible en plusieurs langues. Vous pourrez choisir la langue dans le menu.

- **Interface adaptative** : L'interface s'adapte à toutes résolutions de 800x600 à 4K (non testé au-delà de 1920x1080).

- **Mise à jour automatique** : l'application se relance automatiquement après une mise à jour.

- **Systèmes et Extensions des fichiers** : à la première utilisation, RGSX lit `es_systems.cfg` (RetroBat/Batocera) et génère `/saves/ports/rgsx/rom_extensions.json` avec les extensions autorisées par système. Ainsi que la liste des plateformes prises en charge par le système.

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

### Méthode Automatique : BATOCERA / KNULLI

- Sur un PC lancer un terminal XTERM depuis le menu F1>Applications
- Depuis un autre équipement sur le réseau avec application Putty ou autre logiciel prenant en charge le SSH (connectez vous à l'IP user=root pass=linux)

**Entrez la commande :**
**`curl -L bit.ly/rgsx-install | sh`**
  
Patientez et regardez le retour à l'écran ou sur la commande.

Vous trouverez RGSX dans le système "PORTS" ou "Jeux Amateurs et portages" (et physiquement dans `/roms/ports/RGSX` et `/roms/windows/rgsx` pour Retrobat.

Mettez à jour la liste des jeux via : `Menu > Paramètres de jeux > Mettre à jour la liste des jeux` si l'application n'apparaît pas !

---

### Méthode manuelle (Retrobat / Batocera)

- Téléchargez le contenu du dépôt en zip : https://github.com/RetroGameSets/RGSX/archive/refs/heads/main.zip
- Extraire le fichier zip dans le dossier ROMS de votre installation (pour Batocera, seulement le dossier PORTS, pour Retrobat : PORTS et WINDOWS)
- Vous aurez donc les dossiers `/roms/ports/RGSX` et `/roms/windows/rgsx`
- Mettez à jour la liste des jeux via : `Menu > Paramètres de jeux > Mettre à jour la liste des jeux` si l'application n'apparaît pas !

---

## 🏁 Premier démarrage

- Vous trouverez RGSX dans le système "WINDOWS" sur Retrobat et dans "PORTS" ou "Jeux Amateurs et portages" 
- Au premier lancement, l'application importera automatiquement la configuration des contrôles depuis des fichiers pré-configurés dans /roms/ports/RGSX/assets/controls si votre manette est reconnue
- L'application téléchargera toutes les données nécessaires automatiquement ensuite (images des systèmes, liste des jeux, etc.)

INFO : pour retrobat au premier lancement, l'application téléchargera Python dans le dossier /system/tools/python qui est nécessaire pour faire fonctionner l'application. Le fichier fait environ 50 Mo et va assez vite à télécharger mais il n'y a aucun retour visuel à l'écran, qui va rester figé sur le chargement de RGSX pendant quelques secondes. Vous trouvez le log d'installation dans `/roms/ports/RGSX-INSTALL.log` à fournir en cas de problème.

---

## 🕹️ Utilisation

### Navigation dans les menus

- Utilisez les touches directionnelles (D-Pad, flèches du clavier) pour naviguer entre les plateformes, jeux et options.
- Appuyez sur la touche configurée comme start (par défaut, **P** ou bouton Start sur la manette) pour ouvrir le menu pause. Depuis ce menu, accédez à toute la configuration de l'application.
- Vous pouvez aussi, depuis le menu, régénérer le cache de la liste des systèmes/jeux/images pour être sûr d'avoir les dernières mises à jour.

---

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

- Dans le menu pause, sélectionnez **Reconfigurer controles**.
- Suivez les instructions à l'écran pour mapper chaque action en maintenant la touche ou le bouton pendant 3 secondes.
- Les noms des boutons s'affichent automatiquement selon votre manette (A, B, X, Y, LB, RB, LT, RT, etc.).
- La configuration est compatible avec toutes les manettes supportées par EmulationStation.
- En cas de problème de contrôles ou configuration corrompue, supprimez le fichier : `/saves/ports/rgsx/controls.json` s'il existe puis redémarrez l'application (il sera recréé automatiquement).

---

### Historique

- Accédez à l'historique des téléchargements via le menu pause ou en appuyant sur la touche historique (par défaut, **H**).
- Sélectionnez un jeu pour le retélécharger si nécessaire en cas d'erreur ou annulation.
- Videz tout l'historique via le bouton **EFFACER** dans le menu historique. Les jeux ne sont pas effacés seulement la liste.
- Annulez un téléchargement avec le bouton **RETOUR**

---

### Logs

Les logs sont enregistrés dans `/roms/ports/RGSX/logs/RGSX.log` sur batocera et sur Retrobat pour diagnostiquer les problèmes et seront à partager pour tout support.

---

## 🔄 Journal des modifications
Toutes les infos sur discord ou sur les commit github.

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
├── RGSX-INSTALL.log         # LOG d'installation uniquement
└── RGSX/
│   └──── __main__.py          # Point d'entrée principal de l'application.
│   ├──── controls.py          # Gestion des événements de navigation dans les menus.
│   ├──── controls_mapper.py   # Configuration des contrôles
│   ├──── display.py           # Rendu des interfaces graphiques avec Pygame.
│   ├──── config.py            # Configuration globale (chemins, paramètres, etc.).
│   ├──── rgsx_settings.py     # Gestion unifiée des paramètres de l'application.
│   ├──── network.py           # Gestion des téléchargements de jeux.
│   ├──── history.py           # Gestion de l'historique des téléchargements.
│   ├──── language.py          # Gestion du support multilingue.
│   ├──── accessibility.py     # Gestion des paramètres d'accessibilité.
│   ├──── utils.py             # Fonctions utilitaires (wrap du texte, troncage etc.).
│   ├──── update_gamelist.py   # Mise à jour de la liste des jeux (Batocera/Knulli).
│   └──── update_gamelist_windows.py  # MAJ gamelist retrobat au lancement.
└────logs/
│   └──── RGSX.log         # Fichier de logs.
└── assets/              # Ressources de l'application (polices, exécutables, musique).
    └──── controls/        # Fichiers de configuration des contrôles pré-définis
    └──── languages/       # Fichiers de traduction


/saves/ports/RGSX/
│
├── systems_list.json    # Liste des systèmes / dossiers / images.
├── games/               # Liens des jeux / plateformes
├── images/              # Images des plateformes.
├── rgsx_settings.json   # Fichier de configuration des paramètres.
├── controls.json        # Fichier de mappage des contrôles manuel
├── history.json         # Base de données de l'historique de téléchargements
├── rom_extensions.json  # Généré depuis es_systems.cfg : extensions autorisées
├── 1FichierAPI.txt      # Clé API 1fichier
└── AllDebridAPI.txt     # Clé API AllDebrid
```

---

## 🤝 Contribution

### Signaler un bug

1. Consultez les logs dans `/roms/ports/RGSX/logs/RGSX.log`.
2. Envoyez un message sur le discord avec le log complet et une description du problème.
- Lien Discord : https://discord.gg/Vph9jwg3VV

### Proposer une fonctionnalité

- Discutez de votre idée sur le discord pour obtenir des retours. 
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

## ⚠️ Problèmes connus

- (Aucun listé actuellement)

---

## 📝 Licence

Ce projet est libre. Vous êtes libre de l'utiliser, le modifier et le distribuer selon les termes de cette licence.

Développé avec ❤️ pour les amateurs de jeux rétro.
