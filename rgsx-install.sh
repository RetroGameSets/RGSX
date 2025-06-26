#!/bin/bash
# Script pour télécharger et installer l'application RGSX depuis retrogamesets.fr
# et mettre à jour gamelist.xml pour ajouter l'entrée RGSX
# Supprime rgsx-install.sh et RGSX.zip après une installation réussie
# Affiche des messages informatifs sur la console (mode CONSOLE) ou via xterm (mode DISPLAY)

# Variables
URL="https://retrogamesets.fr/softs/RGSX.zip"
ZIP_FILE="/tmp/rgsx.zip"
DEST_DIR="/userdata/roms/ports"
RGSX_DIR="${DEST_DIR}/RGSX"
GAMELIST_FILE="${DEST_DIR}/gamelist.xml"
UPDATE_GAMELIST_PY="${RGSX_DIR}/update_gamelist.py"
LOG_DIR="${DEST_DIR}/logs"
LOG_FILE="${LOG_DIR}/rgsx_install.log"
TEMP_LOG="/tmp/rgsx_install_temp.log"
SCRIPT_FILE="${DEST_DIR}/rgsx-install.sh"
XTERM="/usr/bin/xterm"
MODE="DISPLAY"  # Par défaut, mode graphique pour PORTS
TEXT_SIZE="24"  # Taille de police pour xterm
TEXT_COLOR="green"

# Chemins absolus pour les commandes
CURL="/usr/bin/curl"
WGET="/usr/bin/wget"
UNZIP="/usr/bin/unzip"
PING="/bin/ping"
RM="/bin/rm"
MKDIR="/bin/mkdir"
CHMOD="/bin/chmod"
FIND="/usr/bin/find"
PYTHON3="/usr/bin/python3"
SYNC="/bin/sync"
SLEEP="/bin/sleep"
LS="/bin/ls"
CAT="/bin/cat"
WHOAMI="/usr/bin/whoami"
ENV="/usr/bin/env"
TOUCH="/bin/touch"
DF="/bin/df"
MOUNT="/bin/mount"
NSLOOKUP="/usr/bin/nslookup"

# Vérifier le mode (DISPLAY ou CONSOLE)
if [[ "$1" = "CONSOLE" ]] || [[ "$1" = "console" ]]; then
    MODE="CONSOLE"
fi

# Fonction pour journaliser avec horodatage dans les fichiers de log
log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    if [ -d "$LOG_DIR" ] && [ -w "$LOG_DIR" ]; then
        echo "[$timestamp] $1" >> "$LOG_FILE" 2>&1
    else
        echo "[$timestamp] $1" >> "$TEMP_LOG" 2>&1
    fi
}

# Fonction pour afficher des messages informatifs (console ou xterm)
console_log() {
    local message="[RGSX Install] $1"
    log "$message"
    if [ "$MODE" = "DISPLAY" ] && [ -x "$XTERM" ]; then
        echo "$message" >> /tmp/rgsx_install_display.log
    elif [ "$MODE" = "CONSOLE" ]; then
        echo "$message"
    fi
}

# Fonction pour exécuter une commande et journaliser son exécution
run_command() {
    local cmd_name="$2"
    log "Exécution de la commande : $1"
    output=$(eval "$1" 2>&1)
    local exit_code=$?
    log "Sortie de '$cmd_name' :"
    log "$output"
    log "Code de retour : $exit_code"
    return $exit_code
}

# Fonction pour gérer les erreurs avec journalisation et message console/xterm
error_exit() {
    local error_msg="$1"
    log "Erreur fatale : $error_msg"
    console_log "Erreur lors de l'installation : $error_msg"
    console_log "Consultez $LOG_FILE pour plus de détails."
    log "Nettoyage du fichier ZIP temporaire : $ZIP_FILE"
    if [ -f "$ZIP_FILE" ]; then
        run_command "$RM -f $ZIP_FILE" "rm_zip"
    fi
    log "Arrêt du script avec code d'erreur 1"
    if [ "$MODE" = "DISPLAY" ] && [ -x "$XTERM" ]; then
        $XTERM -fullscreen -fg $TEXT_COLOR -bg black -fs $TEXT_SIZE -e "cat /tmp/rgsx_install_display.log; echo 'Appuyez sur une touche pour quitter...'; read -n 1; exit"
        rm -f /tmp/rgsx_install_display.log
    fi
    exit 1
}

# Configurer l'environnement graphique pour xterm
if [ "$MODE" = "DISPLAY" ]; then
    export DISPLAY=:0.0
    if [ -x "$XTERM" ]; then
        cp $XTERM /tmp/rgsx-install-xterm && chmod 777 /tmp/rgsx-install-xterm
        echo "[RGSX Install] Démarrage de l'installation de RGSX..." > /tmp/rgsx_install_display.log
        # Lancer xterm en arrière-plan pour afficher la progression
        /tmp/rgsx-install-xterm -fullscreen -fg $TEXT_COLOR -bg black -fs $TEXT_SIZE -e "tail -f /tmp/rgsx_install_display.log" &
        XTERM_PID=$!
        sleep 1  # Attendre que xterm démarre
    else
        log "xterm non disponible, passage en mode journalisation uniquement."
        MODE="CONSOLE"
    fi
else
    console_log "Démarrage de l'installation de RGSX..."
fi

# Vérifier l'accessibilité de /tmp pour le journal temporaire
log "Vérification de l'accessibilité de /tmp pour le journal temporaire"
run_command "$TOUCH $TEMP_LOG && $RM $TEMP_LOG" "test_tmp_access" || error_exit "Le répertoire /tmp n'est pas accessible en écriture."

# Nettoyer les dossiers mal créés
log "Vérification des dossiers mal créés sous /userdata"
if [ -d "/userdata/\"/userdata/roms/ports\"" ]; then
    log "Suppression du dossier incorrect /userdata/\"/userdata/roms/ports\""
    run_command "$RM -rf /userdata/\\\"/userdata/roms/ports\\\"" "rm_incorrect_dir"
fi

# Journaliser l'état du système de fichiers
log "État du système de fichiers :"
run_command "$DF -h" "df_filesystem"
log "Points de montage :"
run_command "$MOUNT" "mount_points"

# Vérifier et créer le répertoire /userdata/roms/ports
console_log "Création du répertoire $DEST_DIR..."
log "Vérification et création du répertoire $DEST_DIR"
run_command "$MKDIR -p $DEST_DIR" "mkdir_dest_dir" || error_exit "Impossible de créer $DEST_DIR."
log "Vérification de l'existence de $DEST_DIR"
if [ ! -d "$DEST_DIR" ]; then
    error_exit "$DEST_DIR n'a pas été créé."
fi
log "Permissions de $DEST_DIR après création"
run_command "$LS -ld $DEST_DIR" "ls_dest_dir"
if [ ! -w "$DEST_DIR" ]; then
    log "Tentative de correction des permissions de $DEST_DIR"
    run_command "$CHMOD u+w $DEST_DIR" "chmod_dest_dir" || error_exit "Impossible de rendre $DEST_DIR accessible en écriture."
fi

# Créer le répertoire des logs
log "Création du répertoire des logs : $LOG_DIR"
run_command "$MKDIR -p $LOG_DIR" "mkdir_log_dir" || error_exit "Impossible de créer $LOG_DIR."

# Copier le journal temporaire dans LOG_FILE
if [ -f "$TEMP_LOG" ] && [ -d "$LOG_DIR" ]; then
    log "Copie du journal temporaire $TEMP_LOG vers $LOG_FILE"
    run_command "$CAT $TEMP_LOG >> $LOG_FILE" "copy_temp_log"
    run_command "$RM -f $TEMP_LOG" "rm_temp_log"
fi

# Journaliser l'environnement d'exécution
log "Utilisateur actuel :"
run_command "$WHOAMI" "whoami"
log "Variables d'environnement :"
run_command "$ENV" "env"
log "Chemin PATH : $PATH"

# Vérifier les dépendances
log "Vérification des commandes nécessaires"
for cmd in "$CURL" "$UNZIP" "$PING" "$RM" "$MKDIR" "$CHMOD" "$FIND" "$PYTHON3" "$SYNC" "$SLEEP" "$LS" "$CAT" "$TOUCH" "$DF" "$MOUNT"; do
    if [ ! -x "$cmd" ]; then
        error_exit "Commande $cmd non trouvée ou non exécutable."
    fi
    log "Commande $cmd : OK"
done
if [ -x "$WGET" ]; then
    log "Commande $WGET : OK"
else
    log "Commande $WGET : Non disponible, utilisation de curl uniquement."
fi
if [ -x "$NSLOOKUP" ]; then
    log "Commande $NSLOOKUP : OK"
else
    log "Commande $NSLOOKUP : Non disponible."
fi

# Vérifier la connexion Internet
log "Test de connexion Internet..."
run_command "$PING -q www.google.fr -c 1" "ping_google" || error_exit "Pas de connexion Internet."

# Tester la résolution DNS
log "Test de résolution DNS pour retrogamesets.fr"
if [ -x "$NSLOOKUP" ]; then
    run_command "$NSLOOKUP retrogamesets.fr" "nslookup_retrogamesets"
fi
run_command "$PING -c 1 retrogamesets.fr" "ping_retrogamesets"

# Télécharger le ZIP avec curl
console_log "Téléchargement de RGSX..."
log "Tentative de téléchargement avec curl : $URL vers $ZIP_FILE..."
run_command "$CURL -L --insecure -v -o $ZIP_FILE $URL" "curl_download"
if [ $? -ne 0 ]; then
    log "Échec du téléchargement avec curl, tentative avec wget si disponible..."
    if [ -x "$WGET" ]; then
        run_command "$WGET --no-check-certificate -O $ZIP_FILE $URL" "wget_download" || error_exit "Échec du téléchargement avec wget."
    else
        error_exit "Échec du téléchargement avec curl et wget non disponible."
    fi
fi
log "Détails du fichier téléchargé :"
run_command "$LS -l $ZIP_FILE" "ls_zip_file"

# Vérifier si le fichier ZIP existe
log "Vérification de l'existence de $ZIP_FILE"
if [ ! -f "$ZIP_FILE" ]; then
    error_exit "Le fichier ZIP $ZIP_FILE n'a pas été téléchargé."
fi
log "Fichier $ZIP_FILE trouvé."

# Vérifier si le fichier ZIP est valide
log "Vérification de l'intégrité du fichier ZIP : $ZIP_FILE"
run_command "$UNZIP -t $ZIP_FILE" "unzip_test" || error_exit "Le fichier ZIP est corrompu ou invalide."
log "Contenu du ZIP :"
run_command "$UNZIP -l $ZIP_FILE" "unzip_list"

# Supprimer l'ancien dossier RGSX s'il existe
if [ -d "$RGSX_DIR" ]; then
    log "Suppression de l'ancien dossier $RGSX_DIR..."
    run_command "$RM -rf $RGSX_DIR" "rm_rgsx_dir" || error_exit "Impossible de supprimer $RGSX_DIR."
    run_command "$SYNC" "sync_after_rm"
    log "Attente de 2 secondes après suppression..."
    run_command "$SLEEP 2" "sleep_after_rm"
    if [ -d "$RGSX_DIR" ]; then
        error_exit "Le dossier $RGSX_DIR existe toujours après tentative de suppression."
    fi
    log "Ancien dossier $RGSX_DIR supprimé avec succès."
else
    log "Aucun dossier $RGSX_DIR existant trouvé."
fi

# Extraire le ZIP
console_log "Extraction des fichiers..."
log "Extraction de $ZIP_FILE vers $DEST_DIR..."
run_command "$UNZIP -q -o $ZIP_FILE -d $DEST_DIR" "unzip_extract" || error_exit "Échec de l'extraction de $ZIP_FILE."
log "Contenu de $DEST_DIR après extraction :"
run_command "$LS -la $DEST_DIR" "ls_dest_dir_after_extract"

# Vérifier si le dossier RGSX a été extrait
log "Vérification de l'existence de $RGSX_DIR"
if [ ! -d "$RGSX_DIR" ]; then
    error_exit "Le dossier RGSX n'a pas été trouvé dans $DEST_DIR après extraction."
fi
log "Dossier $RGSX_DIR trouvé."

# Rendre les fichiers .sh exécutables
log "Rendre les fichiers .sh exécutables dans $RGSX_DIR..."
run_command "$FIND $RGSX_DIR -type f -name \"*.sh\" -exec $CHMOD +x {} \;" "chmod_sh_files" || log "Avertissement : Impossible de rendre certains fichiers .sh exécutables."
log "Fichiers .sh dans $RGSX_DIR :"
run_command "$FIND $RGSX_DIR -type f -name \"*.sh\" -ls" "find_sh_files"

# Rendre update_gamelist.py exécutable
log "Rendre $UPDATE_GAMELIST_PY exécutable..."
if [ -f "$UPDATE_GAMELIST_PY" ]; then
    run_command "$CHMOD +x $UPDATE_GAMELIST_PY" "chmod_update_gamelist" || log "Avertissement : Impossible de rendre $UPDATE_GAMELIST_PY exécutable."
else
    error_exit "Le script Python $UPDATE_GAMELIST_PY n'existe pas."
fi

# Définir les permissions du dossier RGSX
log "Définition des permissions de $RGSX_DIR..."
run_command "$CHMOD -R u+rwX $RGSX_DIR" "chmod_rgsx_dir" || log "Avertissement : Impossible de définir les permissions de $RGSX_DIR."

# Vérifier les permissions d'écriture
log "Vérification des permissions d'écriture sur $DEST_DIR"
if [ ! -w "$DEST_DIR" ]; then
    error_exit "Le répertoire $DEST_DIR n'est pas accessible en écriture."
fi
log "Permissions d'écriture sur $DEST_DIR : OK"

# Mettre à jour gamelist.xml avec Python
console_log "Mise à jour de gamelist.xml..."
log "Mise à jour de $GAMELIST_FILE avec Python..."
run_command "$PYTHON3 $UPDATE_GAMELIST_PY" "python_update_gamelist" || error_exit "Échec de la mise à jour de $GAMELIST_FILE avec Python."
log "Contenu de $GAMELIST_FILE après mise à jour :"
run_command "$CAT $GAMELIST_FILE" "cat_gamelist"

# Vérifier les permissions du fichier gamelist.xml
log "Définition des permissions de $GAMELIST_FILE..."
run_command "$CHMOD 644 $GAMELIST_FILE" "chmod_gamelist" || log "Avertissement : Impossible de définir les permissions de $GAMELIST_FILE."

# Nettoyer le fichier ZIP temporaire
console_log "Nettoyage des fichiers temporaires..."
log "Nettoyage du fichier ZIP temporaire : $ZIP_FILE"
if [ -f "$ZIP_FILE" ]; then
    run_command "$RM -f $ZIP_FILE" "rm_zip" || log "Avertissement : Impossible de supprimer $ZIP_FILE."
fi

# Nettoyer le fichier ZIP dans /userdata/roms/ports
log "Nettoyage du fichier ZIP dans $DEST_DIR : $DEST_DIR/RGSX.zip"
if [ -f "$DEST_DIR/RGSX.zip" ]; then
    run_command "$RM -f $DEST_DIR/RGSX.zip" "rm_dest_zip" || log "Avertissement : Impossible de supprimer $DEST_DIR/RGSX.zip."
fi



# Finalisation
console_log "Installation réussie ! Actualisez la liste des jeux (F5 ou menu système) pour lancer RGSX."
log "Installation terminée avec succès ! RGSX est installé dans $RGSX_DIR."
log "Actualisez la liste des jeux dans Batocera (F5 ou menu système), puis lancez RGSX depuis PORTS."
log "L'entrée RGSX a été ajoutée à $GAMELIST_FILE."
log "Fin du script avec code de retour 0"
run_command "$PING -q www.google.fr -c 5" "ping_google"

# Afficher la finalisation dans xterm et attendre une entrée utilisateur
if [ "$MODE" = "DISPLAY" ] && [ -x "$XTERM" ]; then
    kill $XTERM_PID 2>/dev/null
    $XTERM -fullscreen -fg $TEXT_COLOR -bg black -fs $TEXT_SIZE -e "cat /tmp/rgsx_install_display.log; echo 'Installation terminée. Appuyez sur une touche pour quitter...'; read -n 1; exit"
    rm -f /tmp/rgsx_install_display.log
    rm -f /tmp/rgsx-install-xterm
fi

# Supprimer le script d'installation
log "Suppression du script d'installation : $SCRIPT_FILE"
if [ -f "$SCRIPT_FILE" ]; then
    run_command "$RM -f $SCRIPT_FILE" "rm_script" || log "Avertissement : Impossible de supprimer $SCRIPT_FILE."
fi

exit 0