# RGSX CLI — Guide d’utilisation

Ce guide couvre toutes les commandes disponibles du CLI et fournit des exemples prêts à copier (Windows PowerShell).

## Nouveau: mode interactif
Vous pouvez maintenant lancer une session interactive et enchaîner les commandes sans retaper `python rgsx_cli.py` à chaque fois :

```powershell
python rgsx_cli.py
```
Vous verrez :
```
RGSX CLI interactive mode. Type 'help' for commands, 'exit' to quit.
rgsx>
```
Dans cette session tapez directement les sous-commandes :
```
rgsx> platforms
rgsx> games --platform snes --search mario
rgsx> download --platform snes --game "Super Mario World (USA).zip"
rgsx> history --tail 10
rgsx> exit
```
Extras :
- `help` ou `?` affiche l’aide globale.
- `exit` ou `quit` quitte la session.
- `--verbose` une fois active les logs détaillés pour toute la session.

## Tableau formaté (platforms)
La commande `platforms` affiche maintenant un tableau ASCII à largeur fixe (sauf avec `--json`) :
```
+--------------------------------+-----------------+
| Nom de plateforme              | Dossier         |
+--------------------------------+-----------------+
| Nintendo Entertainment System  | nes             |
| Super Nintendo Entertainment.. | snes            |
| Sega Mega Drive                | megadrive       |
+--------------------------------+-----------------+
```
Colonnes : 30 caractères pour le nom, 15 pour le dossier (troncature par `...`).

## Aliases & synonymes d’options (mis à jour)
Aliases des sous-commandes :
- `platforms` → `p`
- `games` → `g`
- `download` → `dl`
- `clear-history` → `clear`

Options équivalentes (toutes les formes listées sont acceptées) :
- Plateforme : `--platform`, `--p`, `-p`
- Jeu : `--game`, `--g`, `-g`
- Recherche : `--search`, `--s`, `-s`
- Forcer (download) : `--force`, `-f`
- Mode interactif (download) : `--interactive`, `-i`

Exemples avec alias :
```powershell
python rgsx_cli.py dl -p snes -g "Super Mario World (USA).zip"
python rgsx_cli.py g --p snes --s mario
python rgsx_cli.py p --json
python rgsx_cli.py clear
```

## Sélection ambiguë lors d’un download (nouveau tableau)
Quand vous tentez un téléchargement avec un titre non exact et que le mode interactif est actif (TTY ou `--interactive`), les correspondances s’affichent en tableau :
```
No exact result found for this game: mario super  yoshi
Select a match to download:
+------+--------------------------------------------------------------+------------+
| #    | Title                                                        | Size       |
+------+--------------------------------------------------------------+------------+
| 1    | Super Mario - Yoshi Island (Japan).zip                       | 3.2M       |
| 2    | Super Mario - Yoshi Island (Japan) (Rev 1).zip               | 3.2M       |
| 3    | Super Mario - Yoshi Island (Japan) (Rev 2).zip               | 3.2M       |
| 4    | Super Mario World 2 - Yoshi's Island (USA).zip               | 3.3M       |
| 5    | Super Mario - Yoshi Island (Japan) (Beta) (1995-07-10).zip   | 3.1M       |
+------+--------------------------------------------------------------+------------+
Enter number (or press Enter to cancel):
```
Si vous annulez ou que le mode interactif n’est pas actif, un tableau similaire est affiché (sans le prompt) suivi d’un conseil.

## Recherche améliorée (multi‑tokens) pour `games`
L’option `--search` / `--s` / `-s` utilise maintenant la même logique de classement que les suggestions du download :
1. Correspondance sous-chaîne (position la plus tôt) — priorité 0
2. Séquence de tokens dans l’ordre (non contiguë) — priorité 1 (écart le plus faible)
3. Tous les tokens présents dans n’importe quel ordre — priorité 2 (ensemble de tokens plus petit privilégié)

Les doublons sont dédupliqués en gardant le meilleur score. Ainsi une requête :
```powershell
python rgsx_cli.py games --p snes --s "super mario yoshi"
```
affiche toutes les variantes pertinentes de "Super Mario World 2 - Yoshi's Island" même si l’ordre des mots diffère.

Exemple de sortie :
```
+--------------------------------------------------------------+------------+
| Game Title                                                   | Size       |
+--------------------------------------------------------------+------------+
| Super Mario World 2 - Yoshi's Island (USA).zip               | 3.3M       |
| Super Mario World 2 - Yoshi's Island (Europe) (En,Fr,De).zip | 3.3M       |
| Super Mario - Yoshi Island (Japan).zip                       | 3.2M       |
| Super Mario - Yoshi Island (Japan) (Rev 1).zip               | 3.2M       |
| Super Mario - Yoshi Island (Japan) (Rev 2).zip               | 3.2M       |
+--------------------------------------------------------------+------------+
```
Si aucun résultat n’est trouvé, seul l’en-tête est affiché puis un message.

## Prérequis
- Python installé et accessible (le projet utilise un mode headless; aucune fenêtre ne s’ouvrira).
- Exécuter depuis le dossier contenant `rgsx_cli.py`.

## Syntaxe générale (mode classique)
Les options globales peuvent être placées avant ou après la sous-commande.

- Forme 1:
  ```powershell
  python rgsx_cli.py [--verbose] [--force-update|-force-update] <commande> [options]
  ```
- Forme 2:
  ```powershell
  python rgsx_cli.py <commande> [options] [--verbose] [--force-update|-force-update]
  ```

- `--verbose` active les logs détaillés (DEBUG) sur stderr.
- `--force-update` (ou `-force-update`) purge les données locales et force le re-téléchargement du pack de données (systems_list, games/*.json, images).

Quand les données sources sont manquantes, le CLI télécharge et extrait automatiquement le pack (avec progression).

## Commandes

### 1) platforms (`platforms` / `p`) — lister les plateformes
- Options:
  - `--json`: sortie JSON (objets `{ name, folder }`).

Exemples:
```powershell
python rgsx_cli.py platforms
python rgsx_cli.py p --json
python rgsx_cli.py --verbose p
python rgsx_cli.py p --verbose
```

Sortie texte: une ligne par plateforme, au format `Nom<TAB>Dossier`.

### 2) games (`games` / `g`) — lister les jeux d’une plateforme
- Options:
  - `--platform | --p | -p <nom_ou_dossier>` (ex: `n64` ou "Nintendo 64").
  - `--search | --s | -s <texte>`: filtre par sous-chaîne.

Exemples:
```powershell
python rgsx_cli.py games --platform n64
python rgsx_cli.py g --p "Nintendo 64" --s zelda
python rgsx_cli.py g -p n64 --verbose
```

Remarques:
- La plateforme est résolue par nom affiché (platform_name) ou dossier, insensible à la casse.

### 3) download (`download` / `dl`) — télécharger un jeu
- Options:
  - `--platform | --p | -p <nom_ou_dossier>`
  - `--game | --g | -g "<titre exact ou partiel>"`
  - `--force | -f`: ignorer l’avertissement d’extension non supportée.
  - `--interactive | -i`: choisir un titre parmi des correspondances quand aucun exact n’est trouvé.

Exemples:
```powershell
# Titre exact
python rgsx_cli.py dl --p n64 --g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Titre partiel (sélection numérotée si aucun exact)
python rgsx_cli.py dl -p n64 -g "Ocarina of Time (Beta)"

# Forcer malgré extension
python rgsx_cli.py dl -p snes -g "pack_roms.rar" -f

# Verbose après sous-commande
python rgsx_cli.py dl -p n64 -g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip" --verbose
```

Pendant le téléchargement: progression %, taille (MB), vitesse (MB/s). Résultat final aussi dans l’historique.

Notes:
- Les ROMs sont enregistrées dans le dossier plateforme correspondant (ex: `R:\roms\n64`).
- Si le fichier est une archive (zip/rar) et que la plateforme ne supporte pas l’extension, un avertissement apparaît (utiliser `--force`).

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

### 5) clear-history (`clear-history` / `clear`) — vider l’historique
Exemple:
```powershell
python rgsx_cli.py clear
```

### Option globale: --force-update — purge + re-téléchargement des données
- Supprime `systems_list.json`, `games/`, `images/` puis retélécharge/extrait le pack.

Exemples:
```powershell
python rgsx_cli.py --force-update
python rgsx_cli.py p --force-update
```

## Comportements et conseils
- Résolution plateforme: par nom affiché ou dossier, insensible à la casse.
- `--verbose`: utile surtout pour téléchargements/extractions.
- Données manquantes: téléchargement + extraction automatiques.
- Codes de sortie (indicatif):
  - `0`: succès
  - `1`: échec téléchargement/erreur générique
  - `2`: plateforme introuvable
  - `3`: jeu introuvable
  - `4`: extension non supportée (sans `--force`)

## Exemples rapides (copier-coller)
```powershell
# Démarrer le shell interactif
python rgsx_cli.py

# Lister plateformes (alias)
python rgsx_cli.py p

# Lister plateformes (JSON)
python rgsx_cli.py p --json

# Lister jeux N64 avec filtre (synonymes)
python rgsx_cli.py g --p n64 --s zelda

# Télécharger un jeu N64 (titre exact) avec alias
python rgsx_cli.py dl --p n64 --g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Télécharger (titre partiel) + sélection
python rgsx_cli.py dl -p n64 -g "Ocarina of Time"

# Historique (20 dernières entrées)
python rgsx_cli.py history --tail 20

# Purger et recharger le pack
python rgsx_cli.py --force-update
```
