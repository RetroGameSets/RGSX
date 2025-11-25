#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module de filtrage des jeux pour RGSX
Partagé entre l'interface graphique et l'interface web
"""

import re
import logging
from typing import List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class GameFilters:
    """Classe pour gérer les filtres de jeux"""
    
    # Régions disponibles
    REGIONS = ['USA', 'Canada', 'Europe', 'France', 'Germany', 'Japan', 'Korea', 'World', 'Other']
    
    def __init__(self):
        # Initialiser toutes les régions en mode 'include' par défaut
        self.region_filters = {region: 'include' for region in self.REGIONS}
        self.hide_non_release = False
        self.one_rom_per_game = False
        self.regex_mode = False
        self.region_priority = ['USA', 'Canada', 'World', 'Europe', 'Japan', 'Other']
    
    def load_from_dict(self, filter_dict: Dict[str, Any]):
        """Charge les filtres depuis un dictionnaire (depuis settings)"""
        loaded_region_filters = filter_dict.get('region_filters', {})
        # Initialiser toutes les régions en 'include' par défaut, puis appliquer celles chargées
        self.region_filters = {region: 'include' for region in self.REGIONS}
        self.region_filters.update(loaded_region_filters)
        
        self.hide_non_release = filter_dict.get('hide_non_release', False)
        self.one_rom_per_game = filter_dict.get('one_rom_per_game', False)
        self.regex_mode = filter_dict.get('regex_mode', False)
        self.region_priority = filter_dict.get('region_priority', 
            ['USA', 'Canada', 'World', 'Europe', 'Japan', 'Other'])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les filtres en dictionnaire (pour sauvegarder dans settings)"""
        return {
            'region_filters': self.region_filters,
            'hide_non_release': self.hide_non_release,
            'one_rom_per_game': self.one_rom_per_game,
            'regex_mode': self.regex_mode,
            'region_priority': self.region_priority
        }
    
    def is_active(self) -> bool:
        """Vérifie si des filtres sont actifs (au moins une région en exclude ou options activées)"""
        has_exclude = any(state == 'exclude' for state in self.region_filters.values())
        return (has_exclude or 
                self.hide_non_release or 
                self.one_rom_per_game)
    
    def reset(self):
        """Réinitialise tous les filtres (toutes les régions en include)"""
        self.region_filters = {region: 'include' for region in self.REGIONS}
        self.hide_non_release = False
        self.one_rom_per_game = False
        self.regex_mode = False
    
    @staticmethod
    def get_game_regions(game_name: str) -> List[str]:
        """Extrait les régions d'un nom de jeu"""
        name = game_name.upper()
        regions = []
        
        # Patterns de région communs - chercher les codes entre parenthèses d'abord
        # Codes de région/langue dans les parenthèses (Ex: (Fr,De) ou (En,Nl))
        paren_content = re.findall(r'\(([^)]+)\)', name)
        for content in paren_content:
            # Codes de langue/région séparés par virgules
            codes = [c.strip() for c in content.split(',')]
            for code in codes:
                if code in ['FR', 'FRA']:
                    if 'France' not in regions:
                        regions.append('France')
                elif code in ['DE', 'GER', 'DEU']:
                    if 'Germany' not in regions:
                        regions.append('Germany')
                elif code in ['EN', 'ENG'] or code.startswith('EN-'):
                    # EN peut être USA, Europe ou autre - on vérifie le contexte
                    if 'EU' in codes or 'EUR' in codes:
                        if 'Europe' not in regions:
                            regions.append('Europe')
                elif code in ['ES', 'ESP', 'SPA']:
                    if 'Other' not in regions:
                        regions.append('Other')
                elif code in ['IT', 'ITA']:
                    if 'Other' not in regions:
                        regions.append('Other')
                elif code in ['NL', 'NLD', 'DU', 'DUT']:
                    if 'Europe' not in regions:
                        regions.append('Europe')
                elif code in ['PT', 'POR']:
                    if 'Other' not in regions:
                        regions.append('Other')
        
        # Patterns de région complets (mots entiers)
        if 'USA' in name or 'US)' in name or re.search(r'\bUS\b', name):
            if 'USA' not in regions:
                regions.append('USA')
        if 'CANADA' in name or 'CA)' in name:
            if 'Canada' not in regions:
                regions.append('Canada')
        if 'EUROPE' in name or 'EU)' in name or re.search(r'\bEU\b', name):
            if 'Europe' not in regions:
                regions.append('Europe')
        if 'FRANCE' in name or 'FR)' in name:
            if 'France' not in regions:
                regions.append('France')
        if 'GERMANY' in name or 'DE)' in name or 'GER)' in name:
            if 'Germany' not in regions:
                regions.append('Germany')
        if 'JAPAN' in name or 'JP)' in name or 'JPN)' in name or re.search(r'\bJP\b', name):
            if 'Japan' not in regions:
                regions.append('Japan')
        if 'KOREA' in name or 'KR)' in name or 'KOR)' in name:
            if 'Korea' not in regions:
                regions.append('Korea')
        if 'WORLD' in name:
            if 'World' not in regions:
                regions.append('World')
        
        # Autres régions
        if re.search(r'\b(AUSTRALIA|ASIA|BRAZIL|CHINA|RUSSIA|SCANDINAVIA|'
                     r'SPAIN|ITALY)\b', name):
            if 'Other' not in regions:
                regions.append('Other')
        
        # Si aucune région trouvée
        if not regions:
            regions.append('Other')
        
        return regions
    
    @staticmethod
    def is_non_release_game(game_name: str) -> bool:
        """Vérifie si un jeu est une version non-release (demo, beta, proto)"""
        name = game_name.upper()
        non_release_patterns = [
            r'\([^\)]*BETA[^\)]*\)',
            r'\([^\)]*DEMO[^\)]*\)',
            r'\([^\)]*PROTO[^\)]*\)',
            r'\([^\)]*SAMPLE[^\)]*\)',
            r'\([^\)]*KIOSK[^\)]*\)',
            r'\([^\)]*PREVIEW[^\)]*\)',
            r'\([^\)]*TEST[^\)]*\)',
            r'\([^\)]*DEBUG[^\)]*\)',
            r'\([^\)]*ALPHA[^\)]*\)',
            r'\([^\)]*PRE-RELEASE[^\)]*\)',
            r'\([^\)]*PRERELEASE[^\)]*\)',
            r'\([^\)]*UNFINISHED[^\)]*\)',
            r'\([^\)]*WIP[^\)]*\)',
            r'\[[^\]]*BETA[^\]]*\]',
            r'\[[^\]]*DEMO[^\]]*\]',
            r'\[[^\]]*TEST[^\]]*\]'
        ]
        return any(re.search(pattern, name) for pattern in non_release_patterns)
    
    @staticmethod
    def get_base_game_name(game_name: str) -> str:
        """Obtient le nom de base du jeu (sans régions, versions, etc.)"""
        base = game_name
        
        # Supprimer extensions
        base = re.sub(r'\.(zip|7z|rar|gz|iso)$', '', base, flags=re.IGNORECASE)
        
        # Extraire info disque si présent
        disc_info = ''
        disc_match = (re.search(r'\(Dis[ck]\s*(\d+)\)', base, re.IGNORECASE) or
                      re.search(r'\[Dis[ck]\s*(\d+)\]', base, re.IGNORECASE) or
                      re.search(r'Dis[ck]\s*(\d+)', base, re.IGNORECASE) or
                      re.search(r'\(CD\s*(\d+)\)', base, re.IGNORECASE) or
                      re.search(r'CD\s*(\d+)', base, re.IGNORECASE))
        if disc_match:
            disc_info = f' (Disc {disc_match.group(1)})'
        
        # Supprimer contenu entre parenthèses et crochets
        base = re.sub(r'\([^)]*\)', '', base)
        base = re.sub(r'\[[^\]]*\]', '', base)
        
        # Normaliser espaces
        base = re.sub(r'\s+', ' ', base).strip()
        
        # Rajouter info disque
        base = base + disc_info
        
        return base
    
    def get_region_priority(self, game_name: str) -> int:
        """Obtient la priorité de région pour un jeu (pour one-rom-per-game)"""
        # Utiliser la fonction de détection de régions pour être cohérent
        game_regions = self.get_game_regions(game_name)
        
        # Trouver la meilleure priorité parmi toutes les régions détectées
        best_priority = len(self.region_priority)  # Par défaut: priorité la plus basse
        
        for region in game_regions:
            try:
                priority = self.region_priority.index(region)
                if priority < best_priority:
                    best_priority = priority
            except ValueError:
                # La région n'est pas dans la liste de priorité
                continue
        
        return best_priority
    
    def apply_filters(self, games: List[Tuple]) -> List[Tuple]:
        """
        Applique les filtres à une liste de jeux
        games: Liste de tuples (game_name, game_url, size)
        Retourne: Liste filtrée de tuples
        """
        if not self.is_active():
            return games
        
        filtered_games = []
        
        # Filtrage par région
        for game in games:
            game_name = game[0]
            
            # Vérifier les filtres de région
            if self.region_filters:
                game_regions = self.get_game_regions(game_name)
                
                # Vérifier si le jeu a au moins une région incluse
                has_included_region = False
                
                for region in game_regions:
                    filter_state = self.region_filters.get(region, 'include')
                    if filter_state == 'include':
                        has_included_region = True
                        break  # Si on trouve une région incluse, c'est bon
                
                # Le jeu est affiché seulement s'il a au moins une région incluse
                if not has_included_region:
                    continue
            
            # Filtrer les non-release
            if self.hide_non_release and self.is_non_release_game(game_name):
                continue
            
            filtered_games.append(game)
        
        # Appliquer "one rom per game"
        if self.one_rom_per_game:
            filtered_games = self._apply_one_rom_per_game(filtered_games)
        
        return filtered_games
    
    def _apply_one_rom_per_game(self, games: List[Tuple]) -> List[Tuple]:
        """Garde seulement une ROM par jeu selon la priorité de région"""
        games_by_base = {}
        
        for game in games:
            game_name = game[0]
            base_name = self.get_base_game_name(game_name)
            
            if base_name not in games_by_base:
                games_by_base[base_name] = []
            
            games_by_base[base_name].append(game)
        
        # Pour chaque jeu de base, garder celui avec la meilleure priorité
        result = []
        for base_name, game_list in games_by_base.items():
            if len(game_list) == 1:
                result.append(game_list[0])
            else:
                # Trier par priorité de région
                sorted_games = sorted(game_list, 
                                     key=lambda g: self.get_region_priority(g[0]))
                result.append(sorted_games[0])
        
        return result
