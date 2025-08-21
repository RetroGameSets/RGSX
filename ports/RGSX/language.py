import os
import json
import pygame #type: ignore
import logging
import config
import subprocess 
from rgsx_settings import load_rgsx_settings, save_rgsx_settings

logger = logging.getLogger(__name__)

# Langue par défaut et variables globales
DEFAULT_LANGUAGE = "en"
current_language = DEFAULT_LANGUAGE
translations = {}
show_language_selector_on_startup = False


# Mapping optionnel pour normaliser les locales Batocera -> codes 2 lettres
BATOCERA_LOCALE_MAP = {
    "en_US": "en",
    "en_GB": "en",
    "fr_FR": "fr",
    "de_DE": "de",
    "es_ES": "es",
    "it_IT": "it",
    "tr_TR": "tr",
    "zh_CN": "zh",
}

def load_language(lang_code=None):
    """Charge les traductions pour la langue spécifiée ou la langue par défaut."""
    global current_language, translations
    
    if lang_code is None:
        lang_code = DEFAULT_LANGUAGE
    
    lang_file = os.path.join(config.APP_FOLDER, "languages", f"{lang_code}.json")
    
    try:
        if not os.path.exists(lang_file):
            if lang_code != DEFAULT_LANGUAGE:
                logger.warning(f"Fichier de langue {lang_code} non trouvé, utilisation de la langue par défaut")
                return load_language(DEFAULT_LANGUAGE)
            else:
                logger.error(f"Fichier de langue par défaut {lang_file} non trouvé")
                return False
        
        
        with open(lang_file, 'r', encoding='utf-8') as f:
            translations = json.load(f)
        
        current_language = lang_code
        #logger.debug(f"Langue {lang_code} chargée avec succès ({len(translations)} traductions)")
        return True
    
    except Exception as e:
        logger.error(f"Erreur lors du chargement de la langue {lang_code}: {str(e)}")
        if lang_code != DEFAULT_LANGUAGE:
            logger.warning(f"Tentative de chargement de la langue par défaut")
            return load_language(DEFAULT_LANGUAGE)
        return False

def get_text(key, default=None):
    """Récupère la traduction correspondant à la clé."""
    if not translations:
        load_language()
    
    if key in translations:
        return translations[key]
    
    # Si la clé n'existe pas, retourner la valeur par défaut ou la clé elle-même
    if default is not None:
        return default
    
    logger.warning(f"Clé de traduction '{key}' non trouvée dans la langue {current_language}")
    return key

def get_available_languages():
    """Récupère la liste des langues disponibles."""
    
    if not os.path.exists(config.LANGUAGES_FOLDER):
        logger.warning(f"Dossier des langues {config.LANGUAGES_FOLDER} non trouvé")
        return []
    
    languages = []
    for file in os.listdir(config.LANGUAGES_FOLDER):
        if file.endswith(".json"):
            lang_code = os.path.splitext(file)[0]
            languages.append(lang_code)
    
    return languages

def set_language(lang_code):
    """Change la langue courante et sauvegarde la préférence."""
    if load_language(lang_code):
        config.current_language = lang_code
        save_language_preference(lang_code)
        return True
    return False

def save_language_preference(lang_code):
    """Sauvegarde la préférence de langue dans rgsx_settings.json."""
    try:
        settings = load_rgsx_settings()
        settings["language"] = lang_code
        save_rgsx_settings(settings)
        
        logger.debug(f"Préférence de langue sauvegardée: {lang_code}")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la préférence de langue: {str(e)}")
        return False

def load_language_preference():
    """Charge la préférence de langue depuis rgsx_settings.json."""
    global show_language_selector_on_startup
    
    try:
        settings = load_rgsx_settings()
        lang_code = settings.get("language", DEFAULT_LANGUAGE)
        return lang_code
    except Exception as e:
        logger.error(f"Erreur lors du chargement de la préférence de langue: {str(e)}")
        # Recréer le fichier avec le français par défaut
        save_language_preference(DEFAULT_LANGUAGE)
        return DEFAULT_LANGUAGE

def get_language_name(lang_code):
    """Retourne le nom de la langue à partir du code."""
    language_names = {
        "fr": "Français",
        "en": "English",
        "es": "Español",
        "de": "Deutsch",
        "it": "Italiano",
        "pt": "Português",
        "ja": "日本語",
        "zh": "中文",
        "ru": "Русский"
    }
    return language_names.get(lang_code, lang_code)

def draw_language_selector(screen, selected_language_index):
    """Affiche le sélecteur de langue."""
    from display import THEME_COLORS, OVERLAY
    
    # Obtenir les langues disponibles
    available_languages = get_available_languages()
    
    if not available_languages:
        logger.error("Aucune langue disponible")
        return
    
    # Afficher l'overlay
    screen.blit(OVERLAY, (0, 0))
    
    # Titre
    title_text = _("language_select_title")
    title_surface = config.font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, config.screen_height // 4))
    
    # Fond du titre
    title_bg_rect = title_rect.inflate(40, 20)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_bg_rect, border_radius=10)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_bg_rect, 2, border_radius=10)
    screen.blit(title_surface, title_rect)
    
    # Options de langue
    button_height = 60
    button_width = 300
    button_spacing = 20
    
    total_height = len(available_languages) * (button_height + button_spacing) - button_spacing
    start_y = (config.screen_height - total_height) // 2
    
    for i, lang_code in enumerate(available_languages):
        # Obtenir le nom de la langue
        lang_name = get_language_name(lang_code)
        
        # Position du bouton
        button_x = (config.screen_width - button_width) // 2
        button_y = start_y + i * (button_height + button_spacing)
        
        # Dessiner le bouton
        button_color = THEME_COLORS["button_hover"] if i == selected_language_index else THEME_COLORS["button_idle"]
        pygame.draw.rect(screen, button_color, (button_x, button_y, button_width, button_height), border_radius=10)
        pygame.draw.rect(screen, THEME_COLORS["border"], (button_x, button_y, button_width, button_height), 2, border_radius=10)
        
        # Texte du bouton
        text_surface = config.font.render(lang_name, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(button_x + button_width // 2, button_y + button_height // 2))
        screen.blit(text_surface, text_rect)
    
    # Instructions
    instruction_text = _("language_select_instruction")
    instruction_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
    instruction_rect = instruction_surface.get_rect(center=(config.screen_width // 2, config.screen_height - 50))
    screen.blit(instruction_surface, instruction_rect)

def handle_language_menu_events(event, screen):
    """Gère les événements du menu de sélection de langue avec support clavier et manette."""
    available_languages = get_available_languages()
    
    if not available_languages:
        logger.error("Aucune langue disponible")
        config.menu_state = "platform"  # Toujours revenir à platform en cas d'erreur
        config.needs_redraw = True
        return
    
    # Navigation avec les touches du clavier
    if event.type == pygame.KEYDOWN:
        # Navigation vers le haut
        if event.key == pygame.K_UP:
            config.selected_language_index = (config.selected_language_index - 1) % len(available_languages)
            config.needs_redraw = True
            logger.debug(f"Navigation vers le haut dans le sélecteur de langue: {config.selected_language_index}")
        
        # Navigation vers le bas
        elif event.key == pygame.K_DOWN:
            config.selected_language_index = (config.selected_language_index + 1) % len(available_languages)
            config.needs_redraw = True
            logger.debug(f"Navigation vers le bas dans le sélecteur de langue: {config.selected_language_index}")
        
        # Sélection de la langue
        elif event.key == pygame.K_RETURN:
            lang_code = available_languages[config.selected_language_index]
            if set_language(lang_code):
                logger.info(f"Langue changée pour {lang_code}")
                config.current_language = lang_code
                
                # Déterminer l'état suivant en fonction du contexte
                if config.previous_menu_state is None:
                    # Premier démarrage - passer à l'état loading pour charger les plateformes
                    config.menu_state = "loading"
                    logger.debug("Premier démarrage: passage à l'état loading après sélection de la langue")
                elif config.previous_menu_state == "pause_menu":
                    # Si on vient du menu pause, retourner au menu pause avec un message
                    config.menu_state = "restart_popup"
                    config.popup_message = _("language_changed").format(lang_code)
                    config.popup_timer = 2000  # 2 secondes
                    config.previous_menu_state = "platform"  # Pour revenir à l'écran principal après le popup
                    logger.debug("Message de confirmation de changement de langue affiché, retour au menu pause")
                else:
                    # Autre cas, retourner à l'état précédent avec un message
                    config.menu_state = "platform"  # Toujours revenir à platform pour éviter les problèmes
                    logger.debug(f"Retour à l'écran principal après sélection de la langue")
            else:
                # Retour au menu pause en cas d'erreur
                config.menu_state = "platform"  # Toujours revenir à platform en cas d'erreur
            
            config.needs_redraw = True
            logger.debug(f"Sélection de la langue: {lang_code}")
        
        # Annulation (seulement si on n'est pas au démarrage)
        elif event.key == pygame.K_ESCAPE and config.previous_menu_state is not None:
            config.menu_state = "pause_menu"
            config.needs_redraw = True
            logger.debug("Annulation de la sélection de langue, retour au menu pause")
    
    # Support de la manette
    elif event.type == pygame.JOYBUTTONDOWN:
        # Sélection avec le bouton A (généralement 0)
        if event.button == 0:  # Bouton A
            lang_code = available_languages[config.selected_language_index]
            if set_language(lang_code):
                logger.info(f"Langue changée pour {lang_code} (manette)")
                config.current_language = lang_code
                
                # Déterminer l'état suivant en fonction du contexte
                if config.previous_menu_state is None:
                    # Premier démarrage - passer à l'état loading pour charger les plateformes
                    config.menu_state = "loading"
                    logger.debug("Premier démarrage: passage à l'état loading après sélection de la langue (manette)")
                else:
                    config.menu_state = "platform"
            else:
                config.menu_state = "platform"
            config.needs_redraw = True
        
        # Annulation avec le bouton B (généralement 1)
        elif event.button == 1 and config.previous_menu_state is not None:  # Bouton B
            config.menu_state = "pause_menu"
            config.needs_redraw = True
            logger.debug("Annulation de la sélection de langue (manette), retour au menu pause")
    
    # Navigation avec le D-pad
    elif event.type == pygame.JOYHATMOTION:
        if event.value == (0, 1):  # Haut
            config.selected_language_index = (config.selected_language_index - 1) % len(available_languages)
            config.needs_redraw = True
            logger.debug(f"Navigation vers le haut dans le sélecteur de langue (D-pad): {config.selected_language_index}")
        elif event.value == (0, -1):  # Bas
            config.selected_language_index = (config.selected_language_index + 1) % len(available_languages)
            config.needs_redraw = True
            logger.debug(f"Navigation vers le bas dans le sélecteur de langue (D-pad): {config.selected_language_index}")
    
    # Navigation avec les joysticks analogiques
    elif event.type == pygame.JOYAXISMOTION:
        # Joystick gauche vertical (généralement axe 1)
        if event.axis == 1 and abs(event.value) > 0.5:
            if event.value < -0.5:  # Haut
                config.selected_language_index = (config.selected_language_index - 1) % len(available_languages)
                config.needs_redraw = True
                logger.debug(f"Navigation vers le haut dans le sélecteur de langue (joystick): {config.selected_language_index}")
            elif event.value > 0.5:  # Bas
                config.selected_language_index = (config.selected_language_index + 1) % len(available_languages)
                config.needs_redraw = True
                logger.debug(f"Navigation vers le bas dans le sélecteur de langue (joystick): {config.selected_language_index}")


def update_valid_states():
    """Ajoute l'état language_select à la liste des états valides."""
    from controls import VALID_STATES
    if "language_select" not in VALID_STATES:
        VALID_STATES.append("language_select")
        logger.debug("État language_select ajouté aux états valides")

def detect_batocera_language():
    """Tente de lire la langue système de Batocera et retourne un code à 2 lettres, sinon None."""
    try:
        batocera_conf = "/userdata/system/batocera.conf"
        if not os.path.exists(batocera_conf):
            logger.debug("batocera.conf introuvable, détection Batocera ignorée")
            return None

        # batocera-settings-get system.language -> ex: en_US, fr_FR, ...
        res = subprocess.run(
            ["batocera-settings-get", "system.language"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode != 0:
            logger.warning(f"Lecture batocera-settings-get échouée (code {res.returncode}): {res.stderr.strip()}")
            return None

        locale_val = res.stdout.strip()
        if not locale_val:
            logger.warning("Langue Batocera vide")
            return None

        lang2 = BATOCERA_LOCALE_MAP.get(locale_val, locale_val.split("_")[0].lower())
        logger.info(f"Langue Batocera détectée: {locale_val} -> {lang2}")
        return lang2
    except FileNotFoundError:
        logger.debug("Commande batocera-settings-get introuvable")
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la détection de la langue Batocera: {e}")
        return None

def initialize_language():
    """Initialise la langue au démarrage de l'application."""
    global show_language_selector_on_startup
    
    # Vérifier si le fichier de préférence de langue existe
    language_file_exists = os.path.exists(config.RGSX_SETTINGS_PATH)
    
    if not language_file_exists:
        # Tentative de détection Batocera
        detected = detect_batocera_language()
        if detected:
            logger.info(f"Préférence de langue initialisée depuis Batocera: {detected}")
            save_language_preference(detected)
        else:
            logger.info(f"Aucune préférence trouvée, utilisation de la langue par défaut: {DEFAULT_LANGUAGE}")
            save_language_preference(DEFAULT_LANGUAGE)
        show_language_selector_on_startup = False
    else:
        show_language_selector_on_startup = False  # Comportement actuel

    # Charger la préférence de langue
    lang_code = load_language_preference()
    
    # Charger la langue préférée (avec fallback interne déjà géré)
    if load_language(lang_code):
        logger.info(f"Langue chargée au démarrage: {lang_code}")
    else:
        logger.warning(f"Impossible de charger la langue {lang_code}, utilisation de la langue par défaut")
        load_language(DEFAULT_LANGUAGE)
    
    return True

# Alias pour faciliter l'utilisation
_ = get_text