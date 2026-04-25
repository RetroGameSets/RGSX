# 🎮 Retro Game Sets Xtra (RGSX)

**[Support Discord](https://discord.gg/Vph9jwg3VV)** • **[Installation](#-installation)** • **[Documentation anglaise](https://github.com/RetroGameSets/RGSX/blob/main/README.md)** • **[Dépannage / Erreurs courantes](https://github.com/RetroGameSets/RGSX/blob/main/README_FR.md#%EF%B8%8F-d%C3%A9pannage)** •

Un téléchargeur de ROMs gratuit et simple d'utilisation pour Batocera, Knulli et RetroBat, avec support multi-sources.

<p align="center">
  <img width="69%" alt="main" src="https://github.com/user-attachments/assets/a98f1189-9a50-4cc3-b588-3f85245640d8" />
  <img width="30%" alt="aide contrôles" src="https://github.com/user-attachments/assets/38cac7e6-14f2-4e83-91da-0679669822ee" />
</p>
<p align="center">
  <img width="49%" alt="interface web" src="https://github.com/user-attachments/assets/71f8bd39-5901-45a9-82b2-91426b3c31a7" />
  <img width="49%" alt="menu api" src="https://github.com/user-attachments/assets/5bae018d-b7d9-4a95-9f1b-77db751ff24f" />
</p>


---

## 🚀 Installation

### Installation rapide (Batocera / Knulli)

**Accès SSH ou Terminal requis :**
```bash
curl -L bit.ly/rgsx-install | sh
```

Après installation :
1. Mettez à jour les listes de jeux : `Menu > Paramètres des jeux > Mettre à jour la liste des jeux`
2. Trouvez RGSX dans **PORTS** ou **Homebrew and ports**

### Installation manuelle (Tous systèmes)
1. **Télécharger** : [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)
2. **Extraire** :
   - **Batocera/Knulli** : extraire le dossier `ports` dans `/roms/`
   - **RetroBat** : extraire les dossiers `ports` et `windows` dans `/roms/`
3. **Rafraîchir** : `Menu > Paramètres des jeux > Mettre à jour la liste des jeux`

### Mise à jour manuelle (si la mise à jour automatique a échoué)
Télécharger la dernière release : [RGSX_update_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)

**Chemins installés :**
- `/roms/ports/RGSX` (tous systèmes)
- `/roms/windows/RGSX` (RetroBat uniquement)

---

## 🎮 Utilisation

### Premier lancement

- Télécharge automatiquement les images systèmes et les listes de jeux
- Configure automatiquement les contrôles si votre manette est reconnue
- **Contrôles cassés ?** Supprimez `/saves/ports/rgsx/controls.json` puis redémarrez

**Mode clavier** : lorsqu'aucune manette n'est détectée, les contrôles s'affichent sous forme de `[Touche]` au lieu d'icônes.

### Structure du menu pause

**Catégories racine**
- Jeux (téléchargements, scans, visibilité des plateformes)
- Langue (changer la langue de l'interface)
- Contrôles (aide et remap)
- Affichage (layout, polices, moniteur/mode, options visuelles)
- Paramètres (musique, symlink, extraction auto, réseau et statut API)
- Support (génération d'une archive support ZIP/logs)
- Quitter (quitter ou redémarrer)

**Contrôles**
- Voir l'aide des contrôles (affiche les actions actuellement mappées)
- Remapper les contrôles (reconfigurer clavier/manette)

**Affichage**
- Layout (3×3, 3×4, 4×3, 4×4)
- Sous-menu taille de police (UI générale + texte du footer)
- Famille de police (Pixel ou DejaVu)
- Sélection du moniteur (quand plusieurs moniteurs sont détectés)
- Mode d'écran (Windows uniquement)
- Mode léger (rendu plus performant)
- Masquer l'avertissement d'extension inconnue (toggle des warnings d'extensions non supportées)

**Jeux**
- Mettre à jour le cache des jeux (retélécharger les données systèmes/jeux)
- Scanner les ROMs possédées (ajouter vos ROMs locales à l'historique)
- Historique des téléchargements (consulter/gérer les entrées)
- Afficher les plateformes non supportées (toggle des plateformes sans dossier ROM local)
- Filtrer les plateformes (menu de visibilité source/plateforme)

**Paramètres**
- Musique de fond (activer/désactiver)
- Options de symlink (choisir copie/symlink)
- Extraction auto (activation/désactivation)
- Sélecteur du dossier ROMs (définir un dossier ROM racine personnalisé)
- Service Web (Batocera/Knulli) (démarrer l'interface web au boot)
- DNS personnalisé (Batocera/Knulli) (contourner certains blocages ISP/domaine)
- Statut des clés API (vérifier la présence des clés providers)
- Statut de connexion (tester les sites requis updates/sources)

---

## ✨ Fonctionnalités

- 🎯 **Détection intelligente des systèmes** – Détecte automatiquement les systèmes supportés depuis `es_systems.cfg`
- 📦 **Gestion intelligente des archives** – Extrait automatiquement les archives quand un système ne supporte pas les ZIP
- 🔑 **Déblocage premium** – API 1Fichier + fallback AllDebrid/Debrid-Link/Real-Debrid pour des téléchargements illimités
- 🎨 **Personnalisation complète** – Layout (3×3 à 4×4), polices, tailles de police (UI + footer), langues (EN/FR/DE/ES/IT/PT)
- 🎮 **Pensé manette avant tout** – Auto-mapping pour les manettes populaires + remapping personnalisé
- 🔍 **Filtrage avancé** – Recherche par nom, afficher/masquer les systèmes non supportés, filtre de plateformes
- 📊 **Gestion des téléchargements** – File d'attente, historique, notifications de progression
- ♿ **Accessibilité** – Échelle de police séparée pour l'UI et le footer, support du mode clavier uniquement

> ### 🔑 Configuration des clés API
> Pour des téléchargements 1Fichier illimités, ajoutez vos clés API dans `/saves/ports/rgsx/` :
> - `1FichierAPI.txt` – clé API 1Fichier (recommandé)
> - `AllDebridAPI.txt` – fallback AllDebrid (optionnel)
> - `DebridLinkAPI.txt` – fallback Debrid-Link (optionnel)
> - `RealDebridAPI.txt` – fallback Real-Debrid (optionnel)
> 
> **Chaque fichier doit contenir UNIQUEMENT la clé, sans texte supplémentaire.**

### Télécharger des jeux

1. Parcourez les plateformes → Sélectionnez un jeu
2. **Téléchargement direct** : appuyez sur `Confirmer`
3. **File d'attente** : appuyez sur `X` (bouton Ouest)
4. Suivez la progression dans le menu **Historique** ou via les notifications popup

## 🌐 Interface Web (Batocera/Knulli uniquement)

RGSX inclut une interface web qui se lance automatiquement quand vous utilisez RGSX, pour parcourir et télécharger des jeux à distance depuis n'importe quel appareil de votre réseau.

### Accéder à l'interface web

1. **Trouvez l'IP de votre Batocera** :
   - Vérifiez dans le menu Batocera : `Paramètres réseau`
   - Ou depuis un terminal : `ip addr show`

2. **Ouvrez dans un navigateur** : `http://[IP_BATOCERA]:5000` ou `http://BATOCERA:5000`
   - Exemple : `http://192.168.1.100:5000`

3. **Disponible depuis n'importe quel appareil** : téléphone, tablette, PC sur le même réseau

### Fonctionnalités de l'interface web

- 📱 **Compatible mobile** – Design responsive sur tous les formats d'écran
- 🔍 **Parcourir tous les systèmes** – Voir toutes les plateformes et jeux
- ⬇️ **Téléchargements à distance** – Ajouter des téléchargements directement vers Batocera
- 📊 **Statut en temps réel** – Voir les téléchargements actifs et l'historique
- 🎮 **Même liste de jeux** – Utilise les mêmes sources que l'application principale


### Activer/Désactiver le service web au démarrage, sans lancer RGSX

**Depuis le menu RGSX**
1. Ouvrez le **menu pause** (Start/ALTGr)
2. Allez dans **Paramètres > Service Web**
3. Activez/Désactivez **Activer au démarrage**
4. Redémarrez votre appareil


**Configuration du port** : le service web utilise le port `5000` par défaut. Assurez-vous que ce port n'est pas bloqué par votre pare-feu.

---

## 📁 Structure des fichiers

```
/roms/
├── ports/
│   ├── RGSX/
│   │   ├── __main__.py                # Point d'entrée
│   │   ├── controls.py                # Gestion des entrées
│   │   ├── display.py                 # Moteur de rendu
│   │   ├── network.py                 # Gestionnaire de téléchargements
│   │   ├── rgsx_settings.py           # Gestionnaire des paramètres
│   │   ├── assets/controls/           # Profils de manettes
│   │   ├── languages/                 # Traductions (EN/FR/DE/ES/IT/PT)
│   │   └── logs/RGSX.log              # Logs d'exécution
│   ├── gamelist.xml
│   ├── images/
│   └── videos/
└── windows/
    ├── RGSX Retrobat.bat              # Lanceur Windows uniquement (utilisable même sans RetroBat)
    ├── gamelist.xml
    ├── images/
    └── videos/

/saves/ports/rgsx/
├── rgsx_settings.json        # Préférences utilisateur
├── controls.json             # Mapping des contrôles
├── history.json              # Historique des téléchargements
├── systems_list.json         # Systèmes détectés
├── global_search_index.json  # Cache de l'index de recherche globale
├── platform_games_count_cache.json
├── torrent_manifest_cache.json
├── games/                    # Bases de données des jeux (par plateforme)
├── images/                   # Images de plateformes
├── 1FichierAPI.txt           # Clé API 1Fichier
├── AllDebridAPI.txt          # Clé API AllDebrid
├── DebridLinkAPI.txt         # Clé API Debrid-Link
└── RealDebridAPI.txt         # Clé API Real-Debrid
```

---

## 🛠️ Dépannage

| Problème | Solution |
|----------|----------|
| Les contrôles ne fonctionnent pas | Supprimez `/saves/ports/rgsx/controls.json` puis redémarrez, vous pouvez aussi supprimer `/roms/ports/RGSX/assets/controls/xx.json` |
| Aucun jeu ? | Menu Pause > Jeux > Mettre à jour le cache des jeux, puis vérifier Menu Pause > Jeux > Filtrer les plateformes et Afficher les plateformes non supportées |
| Des systèmes manquent dans la liste ? | RGSX lit `es_systems.cfg` pour afficher uniquement les systèmes supportés. Si vous voulez tous les systèmes : Menu Pause > Jeux > Afficher les plateformes non supportées |
| L'application crash | Vérifiez `/roms/ports/RGSX/logs/RGSX.log` ou `/roms/windows/logs/Retrobat_RGSX_log.txt` |
| Changement de layout non appliqué | Redémarrez RGSX après modification du layout |
| Problème de téléchargement de certains jeux ? | Ouvrez Menu Pause > Paramètres > Statut de connexion. Si un ou plusieurs sites requis sont en rouge, activez DNS personnalisé dans Paramètres et redémarrez. Vérifiez aussi les protections ISP/routeur (notamment ASUS web threat blocking). |

**Besoin d'aide ?** Partagez les logs de `/roms/ports/RGSX/logs/` sur [Discord](https://discord.gg/Vph9jwg3VV).

---

## 🤝 Contribution

- **Rapports de bugs** : ouvrez une issue GitHub avec les logs, ou postez sur Discord
- **Demandes de fonctionnalités** : discutez d'abord sur Discord, puis ouvrez une issue
- **Contributions code** : 
  ```bash
  git checkout -b feature/your-feature
  # Tester sur Batocera/RetroBat
  # Soumettre une Pull Request
  ```

---

## 📝 Licence

Logiciel gratuit et open-source. Utilisation, modification et distribution libres.

## Merci à tous les contributeurs et suiveurs du projet

**Si vous voulez soutenir mon projet, vous pouvez m'offrir une bière : https://bit.ly/donate-to-rgsx**
[![Stargazers over time](https://starchart.cc/RetroGameSets/RGSX.svg?variant=adaptive)](https://starchart.cc/RetroGameSets/RGSX)

**Développé avec ❤️ pour la communauté retrogaming.**
