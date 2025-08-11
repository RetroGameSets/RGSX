import xml.etree.ElementTree as ET
import os
import logging
import pygame #type: ignore

logger = logging.getLogger(__name__)

def parse_es_input_config():
    """Parse le fichier es_input.cfg d'EmulationStation et retourne la configuration des contrôles"""
    es_input_path = "/usr/share/emulationstation/es_input.cfg"
    
    if not os.path.exists(es_input_path):
        logger.debug(f"Fichier {es_input_path} non trouvé")
        return None
    
    try:
        tree = ET.parse(es_input_path)
        root = tree.getroot()
        
        # Mapping des boutons EmulationStation vers les actions RGSX
        # Priorité: D-pad > Joystick pour la navigation
        es_to_rgsx_mapping = {
            "b": "confirm",
            "a": "cancel", 
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "pageup": "page_up",
            "pagedown": "page_down",
            "y": "clear_history",
            "x": "history",
            "select": "filter",
            "leftshoulder": "delete",
            "rightshoulder": "space",
            "start": "start"
        }
        
        # Priorité pour les entrées directionnelles (hat > axis)
        direction_priority = {"up": [], "down": [], "left": [], "right": []}
        
        controls_config = {}
        
        # Chercher la première configuration de joystick
        for inputConfig in root.findall("inputConfig"):
            if inputConfig.get("type") == "joystick":
                logger.debug(f"Configuration trouvée pour: {inputConfig.get('deviceName', 'Manette inconnue')}")
                
                # Première passe: collecter toutes les entrées par action
                for input_tag in inputConfig.findall("input"):
                    es_name = input_tag.get("name")
                    es_type = input_tag.get("type")
                    es_id = input_tag.get("id")
                    es_value = input_tag.get("value", "1")
                    
                    logger.debug(f"Entrée trouvée: {es_name} = {es_type}:{es_id} (value={es_value})")
                    
                    if es_name in es_to_rgsx_mapping:
                        rgsx_action = es_to_rgsx_mapping[es_name]
                        
                        if es_type == "hat" and rgsx_action in direction_priority:
                            # Priorité maximale pour le D-pad
                            hat_mapping = {
                                "1": (0, 1),   # Haut
                                "2": (1, 0),   # Droite  
                                "4": (0, -1),  # Bas
                                "8": (-1, 0)   # Gauche
                            }
                            if es_value in hat_mapping:
                                logger.debug(f"D-pad trouvé pour {rgsx_action}: hat {es_id}, value {es_value}")
                                direction_priority[rgsx_action].append(("hat", {
                                    "type": "hat", 
                                    "joy": 0, 
                                    "hat": int(es_id), 
                                    "value": hat_mapping[es_value]
                                }))
                        elif es_type == "axis" and rgsx_action in direction_priority:
                            # Priorité secondaire pour les axes
                            direction = 1 if int(es_value) > 0 else -1
                            logger.debug(f"Axe trouvé pour {rgsx_action}: axis {es_id}, direction {direction}")
                            direction_priority[rgsx_action].append(("axis", {
                                "type": "axis", 
                                "joy": 0, 
                                "axis": int(es_id), 
                                "direction": direction
                            }))
                        elif es_type == "button":
                            controls_config[rgsx_action] = {
                                "type": "button", 
                                "joy": 0, 
                                "button": int(es_id)
                            }
                        elif es_type == "key":
                            controls_config[rgsx_action] = {
                                "type": "key", 
                                "key": int(es_id)
                            }
                
                # Deuxième passe: assigner les directions avec priorité
                for action, entries in direction_priority.items():
                    if entries:
                        logger.debug(f"Priorité pour {action}: {[(e[0], e[1]['type']) for e in entries]}")
                        # Trier par priorité: hat d'abord, puis axis
                        entries.sort(key=lambda x: 0 if x[0] == "hat" else 1)
                        controls_config[action] = entries[0][1]
                        logger.debug(f"Sélectionné pour {action}: {entries[0][1]['type']}")
                
                logger.debug(f"Configuration finale: {controls_config}")
                
                # Forcer l'utilisation du D-pad pour les directions si disponible, sinon clavier
                if any(controls_config.get(action, {}).get("type") == "axis" for action in ["up", "down", "left", "right"]):
                    # Vérifier si une manette est connectée
                    
                    pygame.joystick.init()
                    if pygame.joystick.get_count() > 0:
                        logger.debug("Remplacement des axes par le D-pad pour la navigation")
                        controls_config["up"] = {"type": "hat", "joy": 0, "hat": 0, "value": (0, 1)}
                        controls_config["down"] = {"type": "hat", "joy": 0, "hat": 0, "value": (0, -1)}
                        controls_config["left"] = {"type": "hat", "joy": 0, "hat": 0, "value": (-1, 0)}
                        controls_config["right"] = {"type": "hat", "joy": 0, "hat": 0, "value": (1, 0)}
                    else:
                        logger.debug("Aucune manette détectée, utilisation du clavier pour toutes les actions")
                        controls_config["up"] = {"type": "key", "key": pygame.K_UP}
                        controls_config["down"] = {"type": "key", "key": pygame.K_DOWN}
                        controls_config["left"] = {"type": "key", "key": pygame.K_LEFT}
                        controls_config["right"] = {"type": "key", "key": pygame.K_RIGHT}
                        controls_config["confirm"] = {"type": "key", "key": pygame.K_RETURN}
                        controls_config["cancel"] = {"type": "key", "key": pygame.K_BACKSPACE}
                        controls_config["start"] = {"type": "key", "key": pygame.K_p}
                        controls_config["filter"] = {"type": "key", "key": pygame.K_f}
                        controls_config["history"] = {"type": "key", "key": pygame.K_h}
                        controls_config["clear_history"] = {"type": "key", "key": pygame.K_x}
                        controls_config["page_up"] = {"type": "key", "key": pygame.K_PAGEUP}
                        controls_config["page_down"] = {"type": "key", "key": pygame.K_PAGEDOWN}
                
                # Ajouter les actions manquantes avec des valeurs par défaut
                default_actions = {
                    "confirm": {"type": "key", "key": pygame.K_RETURN},
                    "cancel": {"type": "key", "key": pygame.K_BACKSPACE},
                    "up": {"type": "key", "key": pygame.K_UP},
                    "down": {"type": "key", "key": pygame.K_DOWN},
                    "left": {"type": "key", "key": pygame.K_LEFT},
                    "right": {"type": "key", "key": pygame.K_RIGHT},
                    "page_up": {"type": "key", "key": pygame.K_PAGEUP},
                    "page_down": {"type": "key", "key": pygame.K_PAGEDOWN},
                    "clear_history": {"type": "key", "key": pygame.K_x},
                    "history": {"type": "key", "key": pygame.K_h},
                    "filter": {"type": "key", "key": pygame.K_f},
                    "delete": {"type": "key", "key": pygame.K_DELETE},
                    "space": {"type": "key", "key": pygame.K_SPACE},
                    "start": {"type": "key", "key": pygame.K_p}
                }
                
                for action, default_config in default_actions.items():
                    if action not in controls_config:
                        controls_config[action] = default_config
                
                logger.info(f"Configuration importée depuis EmulationStation pour {len(controls_config)} actions")
                return controls_config
        
        logger.debug("Aucune configuration de joystick trouvée dans es_input.cfg")
        return None
        
    except Exception as e:
        logger.error(f"Erreur lors du parsing de es_input.cfg: {str(e)}")
        return None