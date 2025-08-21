# Migration vers rgsx_settings.json

## Résumé des changements

Ce commit unifie les fichiers de configuration suivants en un seul fichier `rgsx_settings.json` :

- `accessibility.json` → `rgsx_settings.json` (clé: `accessibility`)
- `language.json` → `rgsx_settings.json` (clé: `language`) 
- `music_config.json` → `rgsx_settings.json` (clé: `music_enabled`)
- `symlink_settings.json` → `rgsx_settings.json` (clé: `symlink`)

## Structure du nouveau fichier rgsx_settings.json

```json
{
  "language": "fr",
  "music_enabled": true,
  "accessibility": {
    "font_scale": 1.0
  },
  "symlink": {
    "enabled": false,
    "target_directory": ""
  }
}
```

## Nouveau module rgsx_settings.py

Un nouveau module `rgsx_settings.py` a été créé pour centraliser la gestion des paramètres :

### Fonctions principales :
- `load_rgsx_settings()` : Charge tous les paramètres depuis rgsx_settings.json
- `save_rgsx_settings(settings)` : Sauvegarde tous les paramètres
- `migrate_old_settings()` : Migre automatiquement les anciens fichiers

## Fichiers modifiés

### Nouveau fichier : rgsx_settings.py
- Module dédié à la gestion des paramètres RGSX
- Contient toute la logique de chargement, sauvegarde et migration
- Documentation complète des fonctions

### config.py
- Ajout de `RGSX_SETTINGS_PATH`
- Import des fonctions depuis `rgsx_settings.py`
- Conservation temporaire des anciens chemins pour la migration
- Suppression des fonctions de gestion des paramètres (déplacées vers rgsx_settings.py)

### accessibility.py
- Import des fonctions depuis `rgsx_settings.py`
- Utilisation directe des fonctions importées au lieu de `config.`

### utils.py
- Import des fonctions depuis `rgsx_settings.py`
- Fonctions `load_music_config()` et `save_music_config()` mises à jour

### symlink_settings.py
- Import des fonctions depuis `rgsx_settings.py`
- Fonctions `load_symlink_settings()` et `save_symlink_settings()` mises à jour
- Compatibilité maintenue avec l'ancien format (`use_symlink_path`)

## Migration automatique

Le système détecte automatiquement les anciens fichiers et les migre vers le nouveau format :

1. Au premier lancement, `load_rgsx_settings()` vérifie si `rgsx_settings.json` existe
2. Si absent, il tente de migrer les données depuis les anciens fichiers
3. Les valeurs par défaut sont utilisées si aucun ancien fichier n'est trouvé
4. Le nouveau fichier unifié est créé automatiquement
5. Les anciens fichiers sont automatiquement supprimés après migration réussie
