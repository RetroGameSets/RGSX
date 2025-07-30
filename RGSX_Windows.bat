@echo off
setlocal EnableDelayedExpansion

:: Définir le fichier de log
set LOG_FILE=%CD%\python_execution_log.txt

:: Ajouter un horodatage au début du log
echo [%DATE% %TIME%] Démarrage du script >> "%LOG_FILE%"

:: Afficher un message de démarrage
cls
echo Exécution de __main__.py pour RetroBat...
echo [%DATE% %TIME%] Exécution de __main__.py pour RetroBat >> "%LOG_FILE%"

:: Définir les chemins relatifs
set TOOLS_FOLDER=..\..\..\system\tools
set PYTHON_EXE=python.exe
set MAIN_SCRIPT=__main__.py
set CURRENT_DIR=%CD%
set "PYTHON_EXE_FULL=%CURRENT_DIR%\!TOOLS_FOLDER!\Python\!PYTHON_EXE!"
set "MAIN_SCRIPT_FULL=%CURRENT_DIR%\!MAIN_SCRIPT!"

:: Afficher et logger les variables
echo TOOLS_FOLDER : !TOOLS_FOLDER!
echo [%DATE% %TIME%] TOOLS_FOLDER : !TOOLS_FOLDER! >> "%LOG_FILE%"
echo PYTHON_EXE : !PYTHON_EXE!
echo [%DATE% %TIME%] PYTHON_EXE : !PYTHON_EXE! >> "%LOG_FILE%"
echo MAIN_SCRIPT : !MAIN_SCRIPT!
echo [%DATE% %TIME%] MAIN_SCRIPT : !MAIN_SCRIPT! >> "%LOG_FILE%"
echo CURRENT_DIR : !CURRENT_DIR!
echo [%DATE% %TIME%] CURRENT_DIR : !CURRENT_DIR! >> "%LOG_FILE%"
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
    :: Définir les chemins pour le téléchargement et l'extraction
    set ZIP_URL=https://retrogamesets.fr/softs/python.zip
    echo ZIP_URL : !ZIP_URL!
    echo [%DATE% %TIME%] ZIP_URL : !ZIP_URL! >> "%LOG_FILE%"
    if not exist "!TOOLS_FOLDER!\Python" (
        echo Création du dossier !TOOLS_FOLDER!\Python...
        echo [%DATE% %TIME%] Création du dossier !TOOLS_FOLDER!\Python... >> "%LOG_FILE%"
        mkdir "!TOOLS_FOLDER!\Python"
    )
    set ZIP_FILE=!TOOLS_FOLDER!\python.zip
    echo ZIP_FILE : !ZIP_FILE!
    echo [%DATE% %TIME%] ZIP_FILE : !ZIP_FILE! >> "%LOG_FILE%"
    echo Téléchargement de python.zip...
    echo [%DATE% %TIME%] Téléchargement de python.zip depuis !ZIP_URL!... >> "%LOG_FILE%"
    :: Afficher un message de progression pendant le téléchargement
    echo Téléchargement en cours...
    curl -L "!ZIP_URL!" -o "!ZIP_FILE!"
    if exist "!ZIP_FILE!" (
        echo Téléchargement terminé. Extraction de python.zip...
        echo [%DATE% %TIME%] Téléchargement terminé. Extraction de python.zip vers !TOOLS_FOLDER!\Python... >> "%LOG_FILE%"
        :: Afficher des messages de progression pendant l'extraction
        echo Extraction en cours...
        tar -xf "!ZIP_FILE!" -C "!TOOLS_FOLDER!" --strip-components=0
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