# RGSX CLI — Guide d’utilisation

Ce guide couvre toutes les commandes disponibles du CLI et fournit des exemples prêts à copier (Windows PowerShell).

## Prérequis
- Python installé et accessible (le projet utilise un mode headless; aucune fenêtre ne s’ouvrira).
- Exécuter depuis le dossier contenant `rgsx_cli.py`.

## Syntaxe générale
Les options globales peuvent être placées avant ou après la sous-commande.

- Forme 1:
  ```powershell
  python rgsx_cli.py [--verbose] [--force-update|-force-update] <commande> [options]
  ```
- Forme 2:
  ```powershell
  python rgsx_cli.py <commande> [options] [--verbose] [--force-update|-force-update]
  ```

- `--verbose` active les logs détaillés (DEBUG) sur la sortie standard d’erreur.
- `--force-update` (ou `-force-update`) purge les données locales et force le re-téléchargement du pack de données (systems_list, games/*.json, images).

Lorsque les données sources sont manquantes, le CLI télécharge et extrait automatiquement le pack (avec une barre de progression).

## Commandes

### 1) platforms — lister les plateformes
- Options:
  - `--json`: sortie JSON (objets `{ name, folder }`).

Exemples:
```powershell
python rgsx_cli.py platforms
python rgsx_cli.py platforms --json
python rgsx_cli.py --verbose platforms
python rgsx_cli.py platforms --verbose
```

Sortie texte: une ligne par plateforme, au format `Nom<TAB>Dossier`.

### 2) games — lister les jeux d’une plateforme
- Options:
  - `--platform <nom_ou_dossier>` (ex: `n64` ou "Nintendo 64").
  - `--search <texte>`: filtre par sous-chaîne dans le nom du jeu.

Exemples:
```powershell
python rgsx_cli.py games --platform n64
python rgsx_cli.py games --platform "Nintendo 64" --search zelda
python rgsx_cli.py games --platform n64 --verbose
```

Remarques:
- La plateforme est résolue par nom affiché (platform_name) ou par dossier (folder), sans tenir compte de la casse.

### 3) download — télécharger un jeu
- Options:
  - `--platform <nom_ou_dossier>`
  - `--game "<titre exact ou partiel>"`
  - `--force`: ignorer l’avertissement si l’extension du fichier n’est pas répertoriée comme supportée pour la plateforme.

Exemples:
```powershell
# Titre exact
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Correspondance partielle
# Si aucun titre exact n’est trouvé, le CLI n’autosélectionne plus. Il affiche des correspondances possibles.
python rgsx_cli.py download --platform n64 --game "Ocarina of Time (Beta)"
# ➜ Le CLI proposera une liste de titres potentiels (à relancer ensuite avec le titre exact).

Mode interactif par défaut:
- Si aucun titre exact n’est trouvé et que vous êtes dans un terminal interactif (TTY), une liste numérotée s’affiche automatiquement pour choisir un match et lancer le téléchargement.

# Forcer si l’extension semble non supportée (ex: .rar)
python rgsx_cli.py download --platform snes --game "pack_roms.rar" --force

# Verbose positionné après la sous-commande
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip" --verbose
```

Pendant le téléchargement, une progression en pourcentage, taille (MB) et vitesse (MB/s) s’affiche. Le résultat final est également écrit dans l’historique.

Notes:
- Les ROMs sont enregistrées dans le dossier de la plateforme correspondante (ex: `R:\roms\n64`).
- Si le fichier est une archive (zip/rar) et que la plateforme ne supporte pas l’extension, un avertissement est affiché (vous pouvez utiliser `--force`).

### 4) history — afficher l’historique
- Options:
  - `--tail <N>`: n dernières entrées (défaut: 50)
  - `--json`: sortie JSON

Exemples:
```powershell
python rgsx_cli.py history
python rgsx_cli.py history --tail 20
python rgsx_cli.py history --json
```

### 5) clear-history — vider l’historique
Exemple:
```powershell
python rgsx_cli.py clear-history
```

### Option globale: --force-update — purge + re-téléchargement des données
- Supprime `systems_list.json`, le dossier `games/` et `images/`, puis télécharge/extrait à nouveau le pack de données.

Exemples:
```powershell
# Sans sous-commande: purge + re-téléchargement puis sortie
python rgsx_cli.py --force-update

# Placé après une sous-commande (accepté aussi)
python rgsx_cli.py platforms --force-update
```

## Comportements et conseils
- Résolution de plateforme: par nom affiché ou dossier, insensible à la casse. Pour la commande `games` et `download`, une recherche par sous-chaîne est utilisée si la correspondance exacte n’est pas trouvée.
- Logs `--verbose`: principalement utiles lors des téléchargements/extractions; émis en DEBUG.
- Téléchargement de données manquantes: automatique avec progression harmonisée (téléchargement puis extraction).
- Codes de sortie (indicatif):
  - `0`: succès
  - `1`: échec du téléchargement/erreur générique
  - `2`: plateforme introuvable
  - `3`: jeu introuvable
  - `4`: extension non supportée (sans `--force`)

## Exemples rapides (copier-coller)
```powershell
# Lister plateformes (texte)
python rgsx_cli.py platforms

# Lister plateformes (JSON)
python rgsx_cli.py platforms --json

# Lister jeux N64 avec filtre
python rgsx_cli.py games --platform n64 --search zelda

# Télécharger un jeu N64 (titre exact)
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Télécharger un jeu N64 (titre aproximatif)
python rgsx_cli.py download --platform n64 --game "Ocarina of Time"
Resultat (exemple) : 
No exact result found for this game: Ocarina of Time
Select a match to download:
  1. Legend of Zelda, The - Ocarina of Time (Europe) (Beta) (2003-02-13) (GameCube).zip
  2. Legend of Zelda, The - Ocarina of Time (Europe) (Beta) (2003-02-21) (GameCube) (Debug).zip
  ...
  15. F-Zero X (USA) (Beta) (The Legend of Zelda - Ocarina of Time leftover data).zip

# Voir l’historique (20 dernières entrées)
python rgsx_cli.py history --tail 20

# Purger et recharger les données de listes des systèmes et des jeux
python rgsx_cli.py --force-update
```
