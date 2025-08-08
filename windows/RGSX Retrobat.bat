@echo off
setlocal EnableDelayedExpansion

:: Fichier de log
if not exist %CD%\logs MD %CD%\logs
set LOG_FILE=%CD%\logs\Retrobat_RGSX_log.txt

:: Ajouter un horodatage au début du log
echo [%DATE% %TIME%] Démarrage du script >> "%LOG_FILE%"

:: Afficher un message de démarrage
cls
echo Exécution de __main__.py pour RetroBat...
echo [%DATE% %TIME%] Exécution de __main__.py pour RetroBat >> "%LOG_FILE%"

:: Définir les chemins relatifs et les convertir en absolus
set CURRENT_DIR=%CD%
set PYTHON_EXE=python.exe

:: Détecter le répertoire racine en remontant de deux niveaux depuis le script
pushd "%CURRENT_DIR%\..\.."
set "ROOT_DIR=%CD%"
popd

:: Définir le chemin du script principal selon les spécifications
set "MAIN_SCRIPT=%ROOT_DIR%\roms\ports\__main__.py"

:: Convertir les chemins relatifs en absolus avec pushd/popd
pushd "%ROOT_DIR%\system\tools\Python"
set "PYTHON_EXE_FULL=%CD%\!PYTHON_EXE!"
popd

set "MAIN_SCRIPT_FULL=!MAIN_SCRIPT!"

:: Afficher et logger les variables
echo CURRENT_DIR : !CURRENT_DIR!
echo [%DATE% %TIME%] CURRENT_DIR : !CURRENT_DIR! >> "%LOG_FILE%"
echo ROOT_DIR : !ROOT_DIR!
echo [%DATE% %TIME%] ROOT_DIR : !ROOT_DIR! >> "%LOG_FILE%"
echo PYTHON_EXE_FULL : !PYTHON_EXE_FULL!
echo [%DATE% %TIME%] PYTHON_EXE_FULL : !PYTHON_EXE_FULL! >> "%LOG_FILE%"
echo MAIN_SCRIPT_FULL : !MAIN_SCRIPT_FULL!
echo [%DATE% %TIME%] MAIN_SCRIPT_FULL : !MAIN_SCRIPT_FULL! >> "%LOG_FILE%"

:: Vérifier si l'exécutable Python existe
echo Vérification de python.exe...
echo [%DATE% %TIME%] Vérification de python.exe à !PYTHON_EXE_FULL! >> "%LOG_FILE%"
if not exist "!PYTHON_EXE_FULL!" (
    echo Python.exe non trouvé. Préparation du téléchargement...
    echo [%DATE% %TIME%] Python.exe non trouvé. Préparation du téléchargement... >> "%LOG_FILE%"
    
    :: Créer le dossier Python s'il n'existe pas
    set "TOOLS_FOLDER_FULL=!ROOT_DIR!\system\tools"
    
    if not exist "!TOOLS_FOLDER_FULL!\Python" (
        echo Création du dossier !TOOLS_FOLDER_FULL!\Python...
        echo [%DATE% %TIME%] Création du dossier !TOOLS_FOLDER_FULL!\Python... >> "%LOG_FILE%"
        mkdir "!TOOLS_FOLDER_FULL!\Python"
    )
    
    set ZIP_URL=https://retrogamesets.fr/softs/python.zip
    set "ZIP_FILE=!TOOLS_FOLDER_FULL!\python.zip"
    echo ZIP_URL : !ZIP_URL!
    echo [%DATE% %TIME%] ZIP_URL : !ZIP_URL! >> "%LOG_FILE%"
    echo ZIP_FILE : !ZIP_FILE!
    echo [%DATE% %TIME%] ZIP_FILE : !ZIP_FILE! >> "%LOG_FILE%"
    
    echo Téléchargement de python.zip...
    echo [%DATE% %TIME%] Téléchargement de python.zip depuis !ZIP_URL!... >> "%LOG_FILE%"
    curl -L "!ZIP_URL!" -o "!ZIP_FILE!"
    
    if exist "!ZIP_FILE!" (
        echo Téléchargement terminé. Extraction de python.zip...
        echo [%DATE% %TIME%] Téléchargement terminé. Extraction de python.zip vers !TOOLS_FOLDER_FULL!... >> "%LOG_FILE%"
        tar -xf "!ZIP_FILE!" -C "!TOOLS_FOLDER_FULL!" --strip-components=0
        echo Extraction terminée.
        echo [%DATE% %TIME%] Extraction terminée. >> "%LOG_FILE%"
        del /q "!ZIP_FILE!"
        echo Fichier python.zip supprimé.
        echo [%DATE% %TIME%] Fichier python.zip supprimé. >> "%LOG_FILE%"
    ) else (
        echo Erreur : Échec du téléchargement de python.zip.
        echo [%DATE% %TIME%] Erreur : Échec du téléchargement de python.zip. >> "%LOG_FILE%"
        goto :error
    )
    
    :: Vérifier à nouveau si python.exe existe après extraction
    if not exist "!PYTHON_EXE_FULL!" (
        echo Erreur : python.exe n'a pas été trouvé après extraction à !PYTHON_EXE_FULL!.
        echo [%DATE% %TIME%] Erreur : python.exe n'a pas été trouvé après extraction à !PYTHON_EXE_FULL! >> "%LOG_FILE%"
        goto :error
    )
)
echo python.exe trouvé.
echo [%DATE% %TIME%] python.exe trouvé. >> "%LOG_FILE%"

:: Vérifier si le script Python existe
echo Vérification de __main__.py...
echo [%DATE% %TIME%] Vérification de __main__.py à !MAIN_SCRIPT_FULL! >> "%LOG_FILE%"
if not exist "!MAIN_SCRIPT_FULL!" (
    echo Erreur : __main__.py n'a pas été trouvé à !MAIN_SCRIPT_FULL!.
    echo [%DATE% %TIME%] Erreur : __main__.py n'a pas été trouvé à !MAIN_SCRIPT_FULL! >> "%LOG_FILE%"
    goto :error
)
echo __main__.py trouvé.
echo [%DATE% %TIME%] __main__.py trouvé. >> "%LOG_FILE%"

:: Exécuter le script Python
echo Exécution de __main__.py...
echo [%DATE% %TIME%] Exécution de __main__.py avec !PYTHON_EXE_FULL! >> "%LOG_FILE%"
"!PYTHON_EXE_FULL!" "!MAIN_SCRIPT_FULL!"
if %ERRORLEVEL% equ 0 (
    echo Exécution terminée avec succès.
    echo [%DATE% %TIME%] Exécution de __main__.py terminée avec succès. >> "%LOG_FILE%"
) else (
    echo Erreur : Échec de l'exécution de __main__.py (code %ERRORLEVEL%).
    echo [%DATE% %TIME%] Erreur : Échec de l'exécution de __main__.py avec code d'erreur %ERRORLEVEL%. >> "%LOG_FILE%"
    goto :error
)

:end
echo Tâche terminée.
echo [%DATE% %TIME%] Tâche terminée avec succès. >> "%LOG_FILE%"
exit /b 0

:error
echo Une erreur s'est produite.
echo [%DATE% %TIME%] Une erreur s'est produite. >> "%LOG_FILE%"
exit /b 1