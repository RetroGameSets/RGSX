# 🎮 Retro Game Sets Xtra (RGSX)

**[Support / Aide Discord](https://discord.gg/Vph9jwg3VV)** • **[Installation](#-installation)** • **[Documentation anglaise](https://github.com/RetroGameSets/RGSX/blob/main/README.md)**

Un téléchargeur de ROMs gratuit et facile à utiliser pour Batocera, Knulli et RetroBat avec support multi-sources.

<p align="center">
  <img width="69%" alt="menu plateformes" src="https://github.com/user-attachments/assets/4464b57b-06a8-45e9-a411-cc12b421545a" />
  <img width="30%" alt="aide contrôles" src="https://github.com/user-attachments/assets/38cac7e6-14f2-4e83-91da-0679669822ee" />
</p>
<p align="center">
  <img width="49%" alt="interface web" src="https://github.com/user-attachments/assets/71f8bd39-5901-45a9-82b2-91426b3c31a7" />
  <img width="49%" alt="menu API" src="https://github.com/user-attachments/assets/5bae018d-b7d9-4a95-9f1b-77db751ff24f" />
</p>


---

## 🚀 Installation

### Installation rapide (Batocera / Knulli)

**Accès SSH ou Terminal requis :**
```bash
curl -L bit.ly/rgsx-install | sh
```

Après l'installation :
1. Mettez à jour les listes de jeux : `Menu > Paramètres des jeux > Mettre à jour la liste des jeux`
2. Trouvez RGSX dans **PORTS** ou **Jeux amateurs et portages**

### Installation manuelle (Tous systèmes)
1. **Télécharger** : [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)
2. **Extraire** :
   - **Batocera/Knulli** : extraire le dossier `ports` dans `/roms/`
   - **RetroBat** : extraire les dossiers `ports` et `windows` dans `/roms/`
3. **Rafraîchir** : `Menu > Paramètres des jeux > Mettre à jour la liste des jeux`

### Mise à jour manuelle (si la mise à jour automatique a échoué)
Téléchargez la dernière version : [RGSX_update_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)

**Chemins d'installation :**
- `/roms/ports/RGSX` (tous systèmes)
- `/roms/windows/RGSX` (RetroBat uniquement)

---

## 🎮 Utilisation

### Premier lancement

- Téléchargement automatique des images systèmes et des listes de jeux
- Configuration automatique des contrôles si votre manette est reconnue
- **Contrôles cassés ?** Supprimez `/saves/ports/rgsx/controls.json` puis relancez

**Mode clavier** : lorsqu'aucune manette n'est détectée, les contrôles s'affichent sous forme de `[Touche]` au lieu d'icônes.

### Structure du menu pause

**Contrôles**
- Voir l'aide des contrôles
- Remapper les contrôles

**Affichage**
- Disposition (3×3, 3×4, 4×3, 4×4)
- Taille de police (UI générale)
- Taille de police du footer (texte des contrôles/version)
- Famille de police (polices pixel)
- Masquer l'avertissement d'extension inconnue

**Jeux**
- Historique des téléchargements
+- Mode des sources (RGSX / Personnalisé)
- Mettre à jour le cache des jeux
- Afficher les plateformes non supportées
- Masquer les systèmes premium
- Filtrer les plateformes

**Paramètres**
- Musique de fond (on/off)
- Options de symlink (Batocera)
- Service web (Batocera)
- Gestion des clés API
- Sélection de la langue

---

## ✨ Fonctionnalités

- 🎯 **Détection intelligente des systèmes** – Découverte automatique des systèmes supportés depuis `es_systems.cfg`
- 📦 **Gestion intelligente des archives** – Extraction automatique quand un système ne supporte pas les fichiers ZIP
- 🔑 **Débloquage premium** – API 1Fichier + fallback AllDebrid/Real-Debrid pour des téléchargements illimités
- 🎨 **Entièrement personnalisable** – Disposition (3×3 à 4×4), polices, tailles de police (UI + footer), langues (EN/FR/DE/ES/IT/PT)
- 🎮 **Pensé manette d'abord** – Auto-mapping pour les manettes populaires + remapping personnalisé
- 🔍 **Filtrage avancé** – Recherche par nom, affichage/masquage des systèmes non supportés, filtre de plateformes
- 📊 **Gestion des téléchargements** – File d'attente, historique, notifications de progression
- 🌐 **Sources personnalisées** – Utilisez vos propres URLs de dépôt de jeux
- ♿ **Accessibilité** – Échelles de police séparées pour l'UI et le footer, support du mode clavier seul

> ### 🔑 Configuration des clés API
> Pour des téléchargements 1Fichier illimités, ajoutez vos clés API dans `/saves/ports/rgsx/` :
> - `1FichierAPI.txt` – Clé API 1Fichier (recommandé)
> - `AllDebridAPI.txt` – Fallback AllDebrid (optionnel)
> - `RealDebridAPI.txt` – Fallback Real-Debrid (optionnel)
> 
> **Chaque fichier ne doit contenir QUE la clé, sans texte supplémentaire.**

### Télécharger des jeux

1. Parcourez les plateformes → sélectionnez un jeu
2. **Téléchargement direct** : appuyez sur `Confirmer`
3. **Ajout à la file d'attente** : appuyez sur `X` (bouton Ouest)
4. Suivez la progression dans le menu **Historique** ou via les popups de notification

### Sources de jeux personnalisées

Basculez vers les sources personnalisées via **Menu pause > Jeux > Mode des sources**.

Configurez dans `/saves/ports/rgsx/rgsx_settings.json` :
```json
{
  "sources": {
    "mode": "custom",
    "custom_url": "https://example.com/my-sources.zip"
  }
}
```
**Note** : si le mode personnalisé est activé mais que l'URL est invalide/vide = utilisation de `/saves/ports/rgsx/games.zip`. Vous devez mettre à jour le cache des jeux dans le menu RGSX après avoir corrigé l'URL.

---

## 🌐 Interface web (Batocera/Knulli uniquement)

RGSX inclut une interface web qui se lance automatiquement avec RGSX pour parcourir et télécharger des jeux à distance depuis n'importe quel appareil de votre réseau.

### Accéder à l'interface web

1. **Trouvez l'adresse IP de votre Batocera** :
   - Dans le menu Batocera : `Paramètres réseau`
   - Ou depuis un terminal : `ip addr show`

2. **Ouvrez dans un navigateur** : `http://[IP_BATO]:5000` ou `http://BATOCERA:5000`
   - Exemple : `http://192.168.1.100:5000`

3. **Accessible depuis n'importe quel appareil** : téléphone, tablette, PC sur le même réseau

### Fonctionnalités de l'interface web

- 📱 **Compatible mobile** – Design responsive qui fonctionne sur tous les écrans
- 🔍 **Parcourir tous les systèmes** – Voir toutes les plateformes et les jeux
- ⬇️ **Téléchargements à distance** – Ajouter des téléchargements directement sur votre Batocera
- 📊 **Statut en temps réel** – Voir les téléchargements actifs et l'historique
- 🎮 **Même liste de jeux** – Utilise les mêmes sources que l'application principale


### Activer/Désactiver le service web au démarrage, sans lancer RGSX

**Depuis le menu RGSX**
1. Ouvrez le **menu pause** (Start/ALTGr)
2. Allez dans **Paramètres > Service web**
3. Basculez sur **Activer au démarrage**
4. Redémarrez votre appareil


**Configuration du port** : le service web utilise le port `5000` par défaut. Assurez-vous qu'il n'est pas bloqué par un pare-feu.

---

## 📁 Structure des fichiers

```
/roms/ports/RGSX/
├── __main__.py                # Point d'entrée
├── controls.py                # Gestion des entrées
├── display.py                 # Moteur de rendu
├── network.py                 # Gestionnaire de téléchargements
├── rgsx_settings.py           # Gestionnaire de paramètres
├── assets/controls/           # Profils de manettes
├── languages/                 # Traductions (EN/FR/DE/ES/IT/PT)
└── logs/RGSX.log             # Logs d'exécution

/roms/windows/RGSX/
└── RGSX Retrobat.bat         # Lanceur RetroBat

/saves/ports/rgsx/
├── rgsx_settings.json        # Préférences utilisateur
├── controls.json             # Mappage des contrôles
├── history.json              # Historique des téléchargements
├── rom_extensions.json       # Cache des extensions supportées
├── systems_list.json         # Systèmes détectés
├── games/                    # Bases de données de jeux (par plateforme)
├── images/                   # Images des plateformes
├── 1FichierAPI.txt          # Clé API 1Fichier
├── AllDebridAPI.txt         # Clé API AllDebrid
└── RealDebridAPI.txt        # Clé API Real-Debrid
```

---

## 🛠️ Dépannage

| Problème | Solution |
|----------|----------|
| Contrôles qui ne répondent plus | Supprimer `/saves/ports/rgsx/controls.json` + redémarrer |
| Jeux non affichés | Menu pause > Jeux > Mettre à jour le cache des jeux |
| Téléchargement bloqué | Vérifier les clés API dans `/saves/ports/rgsx/` |
| Crash de l'application | Vérifier `/roms/ports/RGSX/logs/RGSX.log` |
| Changement de layout non pris en compte | Redémarrer RGSX après modification du layout |

**Besoin d'aide ?** Partagez les logs depuis `/roms/ports/RGSX/logs/` sur [Discord](https://discord.gg/Vph9jwg3VV).

---

## 🤝 Contribution

- **Rapports de bugs** : ouvrez une issue GitHub avec les logs ou postez sur Discord
- **Demandes de fonctionnalités** : discutez d'abord sur Discord, puis ouvrez une issue
- **Contributions de code** : 
  ```bash
  git checkout -b feature/your-feature
  # Testez sur Batocera/RetroBat
  # Soumettez une Pull Request
  ```

---

## 📝 Licence

Logiciel libre et open-source. Utilisation, modification et distribution autorisées librement.

## Merci à tous les contributeurs et aux personnes qui suivent l'application

[![Stargazers over time](https://starchart.cc/RetroGameSets/RGSX.svg?variant=adaptive)](https://starchart.cc/RetroGameSets/RGSX)

**Développé avec ❤️ pour la communauté du retrogaming.**

