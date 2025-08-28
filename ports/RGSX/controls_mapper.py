import pygame # type: ignore
import json
import os
import logging
import config
import language
from config import CONTROLS_CONFIG_PATH
from display import draw_gradient
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Chemin du fichier de configuration des contrôles
CONTROLS_CONFIG_PATH = os.path.join(config.SAVE_FOLDER, "controls.json")

# Actions internes de RGSX à mapper

# Actions internes de RGSX à mapper (labels et descriptions traduits dynamiquement)
ACTION_DEFS = [
    {"name": "confirm"},
    {"name": "cancel"},
    {"name": "up"},
    {"name": "down"},
    {"name": "left"},
    {"name": "right"},
    {"name": "start"},
    {"name": "filter"},
    {"name": "page_up"},
    {"name": "page_down"},
    {"name": "history"},
    {"name": "clear_history"},
    {"name": "delete"},
    {"name": "space"},
]

def get_actions(lang=None):
    """Retourne la liste des actions avec labels/descriptions traduits selon la langue courante."""
    actions = []
    for a in ACTION_DEFS:
        name = a["name"]
        display = language.get_text(f"controls_action_{name}", name.capitalize())
        description = language.get_text(f"controls_desc_{name}", "")
        actions.append({"name": name, "display": display, "description": description})
    return actions


# Mappage des valeurs SDL vers les constantes Pygame
SDL_TO_PYGAME_KEY = {
    1073741906: pygame.K_UP,      # Flèche Haut
    1073741905: pygame.K_DOWN,    # Flèche Bas
    1073741904: pygame.K_LEFT,    # Flèche Gauche
    1073741903: pygame.K_RIGHT,   # Flèche Droite
    1073742050: pygame.K_LALT,    # Alt gauche
    1073742054: pygame.K_RALT,    # Alt droit (AltGr)
    1073742049: pygame.K_LCTRL,   # Ctrl gauche
    1073742053: pygame.K_RCTRL,   # Ctrl droit
    1073742048: pygame.K_LSHIFT,  # Shift gauche
    1073742052: pygame.K_RSHIFT,  # Shift droit
}

# Noms lisibles pour les touches clavier
KEY_NAMES = {
    pygame.K_RETURN: "Enter",
    pygame.K_ESCAPE: "Échap",
    pygame.K_SPACE: "Espace",
    pygame.K_UP: "↑",
    pygame.K_DOWN: "↓",
    pygame.K_LEFT: "←",
    pygame.K_RIGHT: "→",
    pygame.K_BACKSPACE: "Backspace",
    pygame.K_TAB: "Tab",
    pygame.K_LALT: "Alt",
    pygame.K_RALT: "AltGR",
    pygame.K_LCTRL: "LCtrl",
    pygame.K_RCTRL: "RCtrl",
    pygame.K_LSHIFT: "LShift",
    pygame.K_RSHIFT: "RShift",
    pygame.K_LMETA: "LMeta",
    pygame.K_RMETA: "RMeta",
    pygame.K_CAPSLOCK: "Verr Maj",
    pygame.K_NUMLOCK: "Verr Num",
    pygame.K_SCROLLOCK: "Verr Déf",
    pygame.K_a: "A",
    pygame.K_b: "B",
    pygame.K_c: "C",
    pygame.K_d: "D",
    pygame.K_e: "E",
    pygame.K_f: "F",
    pygame.K_g: "G",
    pygame.K_h: "H",
    pygame.K_i: "I",
    pygame.K_j: "J",
    pygame.K_k: "K",
    pygame.K_l: "L",
    pygame.K_m: "M",
    pygame.K_n: "N",
    pygame.K_o: "O",
    pygame.K_p: "P",
    pygame.K_q: "Q",
    pygame.K_r: "R",
    pygame.K_s: "S",
    pygame.K_t: "T",
    pygame.K_u: "U",
    pygame.K_v: "V",
    pygame.K_w: "W",
    pygame.K_x: "X",
    pygame.K_y: "Y",
    pygame.K_z: "Z",
    pygame.K_0: "0",
    pygame.K_1: "1",
    pygame.K_2: "2",
    pygame.K_3: "3",
    pygame.K_4: "4",
    pygame.K_5: "5",
    pygame.K_6: "6",
    pygame.K_7: "7",
    pygame.K_8: "8",
    pygame.K_9: "9",
    pygame.K_KP0: "Num 0",
    pygame.K_KP1: "Num 1",
    pygame.K_KP2: "Num 2",
    pygame.K_KP3: "Num 3",
    pygame.K_KP4: "Num 4",
    pygame.K_KP5: "Num 5",
    pygame.K_KP6: "Num 6",
    pygame.K_KP7: "Num 7",
    pygame.K_KP8: "Num 8",
    pygame.K_KP9: "Num 9",
    pygame.K_KP_PERIOD: "Num .",
    pygame.K_KP_DIVIDE: "Num /",
    pygame.K_KP_MULTIPLY: "Num *",
    pygame.K_KP_MINUS: "Num -",
    pygame.K_KP_PLUS: "Num +",
    pygame.K_KP_ENTER: "Num Enter",
    pygame.K_KP_EQUALS: "Num =",
    pygame.K_F1: "F1",
    pygame.K_F2: "F2",
    pygame.K_F3: "F3",
    pygame.K_F4: "F4",
    pygame.K_F5: "F5",
    pygame.K_F6: "F6",
    pygame.K_F7: "F7",
    pygame.K_F8: "F8",
    pygame.K_F9: "F9",
    pygame.K_F10: "F10",
    pygame.K_F11: "F11",
    pygame.K_F12: "F12",
    pygame.K_F13: "F13",
    pygame.K_F14: "F14",
    pygame.K_F15: "F15",
    pygame.K_INSERT: "Inser",
    pygame.K_DELETE: "Suppr",
    pygame.K_HOME: "Début",
    pygame.K_END: "Fin",
    pygame.K_PAGEUP: "Page+",
    pygame.K_PAGEDOWN: "Page-",
    pygame.K_PRINT: "PrintScreen",
    pygame.K_SYSREQ: "SysReq",
    pygame.K_BREAK: "Pause",
    pygame.K_PAUSE: "Pause",
    pygame.K_BACKQUOTE: "`",
    pygame.K_MINUS: "-",
    pygame.K_EQUALS: "=",
    pygame.K_LEFTBRACKET: "[",
    pygame.K_RIGHTBRACKET: "]",
    pygame.K_BACKSLASH: "\\",
    pygame.K_SEMICOLON: ";",
    pygame.K_QUOTE: "'",
    pygame.K_COMMA: ",",
    pygame.K_PERIOD: ".",
    pygame.K_SLASH: "/",
}

def get_controller_button_names():
    """Récupère les noms des boutons depuis es_input.cfg"""
    es_input_path = "/usr/share/emulationstation/es_input.cfg"
    button_names = {}
    
    if not os.path.exists(es_input_path):
        return {i: f"Bouton {i}" for i in range(16)}
    
    try:
        tree = ET.parse(es_input_path)
        root = tree.getroot()
        
        # Mapping des noms ES vers des noms lisibles
        es_button_names = {
            "a": "A", "b": "B", "x": "X", "y": "Y",
            "leftshoulder": "LB", "rightshoulder": "RB",
            "lefttrigger": "LT", "righttrigger": "RT",
            "select": "Select", "start": "Start",
            "leftstick": "L3", "rightstick": "R3"
        }
        
        for inputConfig in root.findall("inputConfig"):
            if inputConfig.get("type") == "joystick":
                for input_tag in inputConfig.findall("input"):
                    if input_tag.get("type") == "button":
                        es_name = input_tag.get("name")
                        button_id = int(input_tag.get("id"))
                        readable_name = es_button_names.get(es_name, es_name.upper())
                        button_names[button_id] = readable_name
                break
    except Exception as e:
        logger.error(f"Erreur parsing es_input.cfg: {e}")
    
    # Compléter avec des noms génériques
    for i in range(16):
        if i not in button_names:
            button_names[i] = f"Bouton {i}"
    
    return button_names

def get_controller_axis_names():
    """Récupère les noms des axes depuis es_input.cfg"""
    es_input_path = "/usr/share/emulationstation/es_input.cfg"
    axis_names = {}
    
    if not os.path.exists(es_input_path):
        return {(i, d): f"Axe {i}{'+' if d > 0 else '-'}" for i in range(8) for d in [-1, 1]}
    
    try:
        tree = ET.parse(es_input_path)
        root = tree.getroot()
        
        # Mapping des noms ES vers des noms lisibles
        es_axis_names = {
            "leftx": "Joy G", "lefty": "Joy G",
            "rightx": "Joy D", "righty": "Joy D",
            "lefttrigger": "LT", "righttrigger": "RT"
        }
        
        for inputConfig in root.findall("inputConfig"):
            if inputConfig.get("type") == "joystick":
                for input_tag in inputConfig.findall("input"):
                    if input_tag.get("type") == "axis":
                        es_name = input_tag.get("name")
                        axis_id = int(input_tag.get("id"))
                        value = int(input_tag.get("value", "1"))
                        direction = 1 if value > 0 else -1
                        
                        if es_name in es_axis_names:
                            base_name = es_axis_names[es_name]
                            if "Joy" in base_name:
                                if "leftx" in es_name or "rightx" in es_name:
                                    axis_names[(axis_id, direction)] = f"{base_name} {'Droite' if direction > 0 else 'Gauche'}"
                                else:
                                    axis_names[(axis_id, direction)] = f"{base_name} {'Bas' if direction > 0 else 'Haut'}"
                            else:
                                axis_names[(axis_id, direction)] = base_name
                break
    except Exception as e:
        logger.error(f"Erreur parsing es_input.cfg: {e}")
    
    # Compléter avec des noms génériques
    for i in range(8):
        for d in [-1, 1]:
            if (i, d) not in axis_names:
                axis_names[(i, d)] = f"Axe {i}{'+' if d > 0 else '-'}"
    
    return axis_names

# Charger les noms depuis es_input.cfg
BUTTON_NAMES = get_controller_button_names()
AXIS_NAMES = get_controller_axis_names()



# Noms pour la croix directionnelle
HAT_NAMES = {
    (0, 1): "D-Pad Haut",
    (0, -1): "D-Pad Bas",
    (-1, 0): "D-Pad Gauche",
    (1, 0): "D-Pad Droite",
}

# Noms pour les boutons de souris
MOUSE_BUTTON_NAMES = {
    1: "Clic Gauche",
    2: "Clic Milieu",
    3: "Clic Droit",
}

# Durée de maintien pour valider une entrée (en millisecondes)
HOLD_DURATION = 1000

JOYHAT_DEBOUNCE = 200  # Délai anti-rebond pour JOYHATMOTION (ms)

def load_controls_config(path=CONTROLS_CONFIG_PATH):
    """Charge la configuration des contrôles depuis controls.json"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        else:
            data = {}
        changed = False

        # Normaliser les alias vers l’action canonique "clear_history"
        # Votre controls.json a "delete_history": mappez-le vers "clear_history"
        if "delete_history" in data and "clear_history" not in data:
            data["clear_history"] = data["delete_history"]
            changed = True
        # Ancien alias éventuel
        if "progress" in data and "clear_history" not in data:
            data["clear_history"] = data["progress"]
            changed = True


        if changed:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        return data
    except Exception as e:
        logger.error(f"Erreur lors du chargement de controls.json : {e}")
        return {}

def save_controls_config(controls_config):
    """Enregistre la configuration des contrôles dans controls.json"""
    try:
        os.makedirs(os.path.dirname(CONTROLS_CONFIG_PATH), exist_ok=True)
        with open(CONTROLS_CONFIG_PATH, "w") as f:
            json.dump(controls_config, f, indent=4)
        logger.info(f"Configuration des contrôles enregistrée avec {len(controls_config)} actions")
        logger.debug(f"Contrôles sauvegardés : {list(controls_config.keys())}")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de controls.json : {e}")
        raise

def get_readable_input_name(event):
    """Retourne un nom lisible pour une entrée (touche, bouton, axe, hat, ou souris)"""
    if event.type == pygame.KEYDOWN:
        key_value = SDL_TO_PYGAME_KEY.get(event.key, event.key)
        return KEY_NAMES.get(key_value, pygame.key.name(key_value) or f"Touche {key_value}")
    elif event.type == pygame.JOYBUTTONDOWN:
        return BUTTON_NAMES.get(event.button, f"Bouton {event.button}")
    elif event.type == pygame.JOYAXISMOTION:
        if abs(event.value) > 0.5:  # Seuil pour détecter un mouvement significatif
            return AXIS_NAMES.get((event.axis, 1 if event.value > 0 else -1), f"Axe {event.axis} {'Positif' if event.value > 0 else 'Négatif'}")
    elif event.type == pygame.JOYHATMOTION:
        if event.value != (0, 0):  # Ignorer la position neutre
            return HAT_NAMES.get(event.value, f"D-Pad {event.value}")
    elif event.type == pygame.MOUSEBUTTONDOWN:
        return MOUSE_BUTTON_NAMES.get(event.button, f"Souris Bouton {event.button}")
    return "Inconnu"


def map_controls(screen):
    """Interface de mappage des contrôles avec maintien de 3 secondes"""
    controls_config = load_controls_config()
    current_action_index = 0
    current_input = None
    input_held_time = 0
    last_input_name = None
    last_frame_time = pygame.time.get_ticks()
    config.needs_redraw = True
    last_joyhat_time = 0
    
    # État des entrées maintenues
    held_keys = set()
    held_buttons = set()
    held_axes = {}
    held_hats = {}
    held_mouse_buttons = set()
    
    actions = get_actions()
    while current_action_index < len(actions):
        if config.needs_redraw:
            progress = min(input_held_time / HOLD_DURATION, 1.0) if current_input else 0.0
            draw_controls_mapping(screen, actions[current_action_index], last_input_name, current_input is not None, progress)
            pygame.display.flip()
            config.needs_redraw = False
        
        current_time = pygame.time.get_ticks()
        delta_time = current_time - last_frame_time
        last_frame_time = current_time
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            # Gestion des relâchements
            if event.type == pygame.KEYUP and event.key in held_keys:
                held_keys.remove(event.key)
                if current_input and current_input["type"] == "key" and current_input["value"] == event.key:
                    current_input = None
                    input_held_time = 0
                    last_input_name = None
                    config.needs_redraw = True
            elif event.type == pygame.JOYBUTTONUP and event.button in held_buttons:
                held_buttons.remove(event.button)
                if current_input and current_input["type"] == "button" and current_input["value"] == event.button:
                    current_input = None
                    input_held_time = 0
                    last_input_name = None
                    config.needs_redraw = True
            elif event.type == pygame.JOYAXISMOTION and abs(event.value) < 0.5:
                if event.axis in held_axes:
                    held_direction = held_axes[event.axis]
                    if current_input and current_input["type"] == "axis" and current_input["value"][0] == event.axis and current_input["value"][1] == held_direction:
                        current_input = None
                        input_held_time = 0
                        last_input_name = None
                        config.needs_redraw = True
                    del held_axes[event.axis]
            elif event.type == pygame.JOYHATMOTION and event.value == (0, 0):
                if event.hat in held_hats:
                    del held_hats[event.hat]
                    if current_input and current_input["type"] == "hat":
                        current_input = None
                        input_held_time = 0
                        last_input_name = None
                        config.needs_redraw = True
                continue
            elif event.type == pygame.MOUSEBUTTONUP and event.button in held_mouse_buttons:
                held_mouse_buttons.remove(event.button)
                if current_input and current_input["type"] == "mouse" and current_input["value"] == event.button:
                    current_input = None
                    input_held_time = 0
                    last_input_name = None
                    config.needs_redraw = True
            
            # Détection des nouvelles entrées
            if event.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION, pygame.MOUSEBUTTONDOWN):
                if event.type == pygame.JOYHATMOTION:
                    if (current_time - last_joyhat_time) < JOYHAT_DEBOUNCE:
                        continue
                    last_joyhat_time = current_time
                
                input_name = get_readable_input_name(event)
                if input_name == "Inconnu":
                    continue
                
                # Déterminer le type et la valeur
                if event.type == pygame.KEYDOWN:
                    input_type = "key"
                    input_value = SDL_TO_PYGAME_KEY.get(event.key, event.key)
                elif event.type == pygame.JOYBUTTONDOWN:
                    input_type = "button"
                    input_value = event.button
                elif event.type == pygame.JOYAXISMOTION and abs(event.value) > 0.5:
                    input_type = "axis"
                    direction = 1 if event.value > 0 else -1
                    input_value = (event.axis, direction)
                    # Ignorer si c'est juste un changement de direction du même axe
                    if event.axis in held_axes and held_axes[event.axis] != direction:
                        continue
                elif event.type == pygame.JOYHATMOTION:
                    input_type = "hat"
                    input_value = event.value
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    input_type = "mouse"
                    input_value = event.button
                else:
                    continue
                
                # Nouvelle entrée détectée
                if (current_input is None or 
                    current_input["type"] != input_type or 
                    current_input["value"] != input_value):
                    current_input = {"type": input_type, "value": input_value}
                    input_held_time = 0
                    last_input_name = input_name
                    config.needs_redraw = True
                
                # Mettre à jour les entrées maintenues
                if input_type == "key":
                    held_keys.add(input_value)
                elif input_type == "button":
                    held_buttons.add(input_value)
                elif input_type == "axis":
                    held_axes[input_value[0]] = input_value[1]
                elif input_type == "hat":
                    held_hats[event.hat] = input_value
                elif input_type == "mouse":
                    held_mouse_buttons.add(input_value)
        
        # Mise à jour du temps de maintien
        if current_input:
            input_held_time += delta_time
            if input_held_time >= HOLD_DURATION:
                action_name = actions[current_action_index]["name"]
                
                # Sauvegarder avec la structure attendue par controls.py
                if current_input["type"] == "key":
                    controls_config[action_name] = {
                        "type": "key",
                        "key": current_input["value"],
                        "display": last_input_name
                    }
                elif current_input["type"] == "button":
                    controls_config[action_name] = {
                        "type": "button",
                        "button": current_input["value"],
                        "display": last_input_name
                    }
                elif current_input["type"] == "axis":
                    axis, direction = current_input["value"]
                    controls_config[action_name] = {
                        "type": "axis",
                        "axis": axis,
                        "direction": direction,
                        "display": last_input_name
                    }
                elif current_input["type"] == "hat":
                    controls_config[action_name] = {
                        "type": "hat",
                        "value": current_input["value"],
                        "display": last_input_name
                    }
                elif current_input["type"] == "mouse":
                    controls_config[action_name] = {
                        "type": "mouse",
                        "button": current_input["value"],
                        "display": last_input_name
                    }
                
                logger.debug(f"Contrôle mappé: {action_name} -> {controls_config[action_name]}")
                current_action_index += 1
                current_input = None
                input_held_time = 0
                last_input_name = None
                config.needs_redraw = True
                
                # Réinitialiser les entrées maintenues
                held_keys.clear()
                held_buttons.clear()
                held_axes.clear()
                held_hats.clear()
                held_mouse_buttons.clear()
            
            config.needs_redraw = True
        
        pygame.time.wait(10)
    
    save_controls_config(controls_config)
    config.controls_config = controls_config
    return True



def draw_controls_mapping(screen, action, last_input, waiting_for_input, hold_progress):
    #Affiche l'interface de mappage des contrôles avec une barre de progression pour le maintien
    draw_gradient(screen, (28, 37, 38), (47, 59, 61))

    # Paramètres de l'interface
    padding_horizontal = 40
    padding_vertical = 30
    padding_between = 15
    border_radius = 24
    border_width = 4
    shadow_offset = 8

    # Titre principal (traduction)
    title_text = language.get_text("controls_mapping_title", "Configuration des contrôles")
    title_surface = config.title_font.render(title_text, True, (255, 255, 255))
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, 80))
    screen.blit(title_surface, title_rect)

    # Instructions (traduction)
    instruction_text = language.get_text("controls_mapping_instruction", "Maintenez pendant 3s pour configurer :")
    description_text = action.get('description', '')
    instruction_surface = config.small_font.render(instruction_text, True, (255, 255, 255))
    description_surface = config.font.render(description_text, True, (200, 200, 200))
    instruction_width, instruction_height = instruction_surface.get_size()
    description_width, description_height = description_surface.get_size()

    # Input détecté (traduction)
    waiting_text = language.get_text("controls_mapping_waiting", "En attente d'une touche ou bouton...")
    press_text = language.get_text("controls_mapping_press", "Appuyez sur une touche ou un bouton")
    input_text = last_input or (waiting_text if waiting_for_input else press_text)
    input_surface = config.small_font.render(input_text, True, (0, 255, 0) if last_input else (255, 255, 255))
    input_width, input_height = input_surface.get_size()

    # Dimensions de la popup
    text_width = max(instruction_width, description_width, input_width)
    text_height = instruction_height + description_height + input_height + 2 * padding_between
    popup_width = text_width + 2 * padding_horizontal
    popup_height = text_height + 40 + 2 * padding_vertical  # +40 pour la barre de progression
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    # Ombre portée
    shadow_rect = pygame.Rect(popup_x + shadow_offset, popup_y + shadow_offset, popup_width, popup_height)
    shadow_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    # Fond semi-transparent
    popup_rect = pygame.Rect(popup_x, popup_y, popup_width, popup_height)
    popup_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(popup_surface, (30, 30, 30, 220), popup_surface.get_rect(), border_radius=border_radius)
    screen.blit(popup_surface, popup_rect.topleft)

    # Bordure blanche
    pygame.draw.rect(screen, (255, 255, 255), popup_rect, border_width, border_radius=border_radius)

    # Afficher les textes
    start_y = popup_y + padding_vertical
    instruction_rect = instruction_surface.get_rect(center=(config.screen_width // 2, start_y + instruction_height // 2))
    screen.blit(instruction_surface, instruction_rect)
    start_y += instruction_height + padding_between
    description_rect = description_surface.get_rect(center=(config.screen_width // 2, start_y + description_height // 2))
    screen.blit(description_surface, description_rect)
    start_y += description_height + padding_between
    input_rect = input_surface.get_rect(center=(config.screen_width // 2, start_y + input_height // 2))
    screen.blit(input_surface, input_rect)
    start_y += input_height + padding_between

    # Barre de progression pour le maintien
    bar_width = 300
    bar_height = 25
    bar_x = (config.screen_width - bar_width) // 2
    bar_y = start_y + 20
    pygame.draw.rect(screen, (50, 50, 50), (bar_x, bar_y, bar_width, bar_height)) 
    progress_width = bar_width * hold_progress
    pygame.draw.rect(screen, (0, 255, 0), (bar_x, bar_y, progress_width, bar_height)) 
    pygame.draw.rect(screen, (255, 255, 255), (bar_x, bar_y, bar_width, bar_height), 2)
    
    # Afficher le pourcentage de progression
    if hold_progress > 0:
        progress_text = f"{int(hold_progress * 100)}%"
        progress_surface = config.small_font.render(progress_text, True, (255, 255, 255))
        progress_rect = progress_surface.get_rect(center=(config.screen_width // 2, bar_y + bar_height + 30))
        screen.blit(progress_surface, progress_rect)