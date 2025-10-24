@echo off
setlocal EnableDelayedExpansion

:: Fichier de log
if not exist "%CD%\logs" MD "%CD%\logs"
set "LOG_FILE=%CD%\logs\Retrobat_RGSX_log.txt"
:: Fichier de log (chemin absolu pour fiabilité)
:: Détecter la racine (ROOT_DIR) d'abord pour construire un chemin stable
set CURRENT_DIR=%CD%
pushd "%CURRENT_DIR%\..\.."
set "ROOT_DIR=%CD%"
popd
if not exist "%ROOT_DIR%\roms\windows\logs" MD "%ROOT_DIR%\roms\windows\logs"
set "LOG_FILE=%ROOT_DIR%\roms\windows\logs\Retrobat_RGSX_log.txt"

:: Ajouter un horodatage au début du log
echo [%DATE% %TIME%] Script start >> "%LOG_FILE%"

:: Afficher un message de démarrage
cls
echo Running __main__.py for RetroBat...
echo [%DATE% %TIME%] Running __main__.py for RetroBat >> "%LOG_FILE%"

:: Définir les chemins relatifs et les convertir en absolus
set CURRENT_DIR=%CD%
set PYTHON_EXE=python.exe

:: Détecter le répertoire racine en remontant de deux niveaux depuis le script
pushd "%CURRENT_DIR%\..\.."
set "ROOT_DIR=%CD%"
popd

:: Définir le chemin du script principal selon les spécifications
set "MAIN_SCRIPT=%ROOT_DIR%\roms\ports\RGSX\__main__.py"

:: Definir le chemin du script de mise à jour de la gamelist Windows
set "UPDATE_GAMELIST_SCRIPT=%ROOT_DIR%\roms\ports\RGSX\update_gamelist_windows.py"

:: Convertir les chemins relatifs en absolus avec pushd/popd
pushd "%ROOT_DIR%\system\tools\Python"
set "PYTHON_EXE_FULL=%ROOT_DIR%\system\tools\Python\!PYTHON_EXE!"
set "PYTHONW_EXE_FULL=%ROOT_DIR%\system\tools\Python\pythonw.exe"
popd

:: Afficher et logger les variables

echo  ROOT_DIR : %ROOT_DIR% >> "%LOG_FILE%"
echo  CURRENT_DIR : !CURRENT_DIR! >> "%LOG_FILE%"
echo  ROOT_DIR : !ROOT_DIR! >> "%LOG_FILE%"
echo  PYTHON_EXE_FULL : !PYTHON_EXE_FULL! >> "%LOG_FILE%"
echo  MAIN_SCRIPT : !MAIN_SCRIPT! >> "%LOG_FILE%"
echo  UPDATE_GAMELIST_SCRIPT : !UPDATE_GAMELIST_SCRIPT! >> "%LOG_FILE%"

:: Vérifier si l'exécutable Python existe
echo Checking python.exe...
echo [%DATE% %TIME%] Checking python.exe at !PYTHON_EXE_FULL! >> "%LOG_FILE%"
if not exist "!PYTHON_EXE_FULL!" (
    echo python.exe not found in system/tools. Preparing to extract..
    echo [%DATE% %TIME%] python.exe not found in system/tools. Preparing to extract.. >> "%LOG_FILE%"
    
    :: Créer le dossier Python s'il n'existe pas
    set "TOOLS_FOLDER_FULL=!ROOT_DIR!\system\tools"
    
    if not exist "!TOOLS_FOLDER_FULL!\Python" (
    echo Creating folder !TOOLS_FOLDER_FULL!\Python...
    echo [%DATE% %TIME%] Creating folder !TOOLS_FOLDER_FULL!\Python... >> "%LOG_FILE%"
        mkdir "!TOOLS_FOLDER_FULL!\Python"
    )
    
    set "ZIP_FILE=%ROOT_DIR%\roms\windows\python.zip"
    echo Extracting ZIP_FILE : !ZIP_FILE!  in /system/tools/Python
    echo [%DATE% %TIME%] ZIP_FILE : !ZIP_FILE! >> "%LOG_FILE%"
 
    if exist "!ZIP_FILE!" (
    echo [%DATE% %TIME%] Extracting python.zip to !TOOLS_FOLDER_FULL!... >> "%LOG_FILE%"
        tar -xf "!ZIP_FILE!" -C "!TOOLS_FOLDER_FULL!\Python" --strip-components=0
    echo Extraction finished.
    echo [%DATE% %TIME%] Extraction finished. >> "%LOG_FILE%"
        del /s /q "!ZIP_FILE!"
    echo python.zip file deleted.
    echo [%DATE% %TIME%] python.zip file deleted. >> "%LOG_FILE%"
    ) else (
    echo Error: Error python.zip not found please download it from github and put in /roms/windows folder.
    echo [%DATE% %TIME%] Error: Error python.zip not found please download it from github and put in /roms/windows folder >> "%LOG_FILE%"
        goto :error
    )
    
    :: Vérifier à nouveau si python.exe existe après extraction
    if not exist "!PYTHON_EXE_FULL!" (
    echo Error: python.exe not found after extraction at !PYTHON_EXE_FULL!.
    echo [%DATE% %TIME%] Error: python.exe not found after extraction at !PYTHON_EXE_FULL! >> "%LOG_FILE%"
        goto :error
    )
)
echo python.exe found.
echo [%DATE% %TIME%] python.exe found. >> "%LOG_FILE%"

:: Vérifier si le script Python existe
echo Checking __main__.py...
echo [%DATE% %TIME%] Checking __main__.py at !MAIN_SCRIPT! >> "%LOG_FILE%"
if not exist "!MAIN_SCRIPT!" (
    echo Error: __main__.py not found at !MAIN_SCRIPT!.
    echo [%DATE% %TIME%] Error: __main__.py not found at !MAIN_SCRIPT! >> "%LOG_FILE%"
    goto :error
)
echo __main__.py found.
echo [%DATE% %TIME%] __main__.py found. >> "%LOG_FILE%"

:: L'étape de mise à jour de la gamelist est désormais appelée depuis __main__.py
echo [%DATE% %TIME%] Skipping external gamelist update (handled in app). >> "%LOG_FILE%"

echo Launching __main__.py (attached)...
echo [%DATE% %TIME%] Preparing to launch main. >> "%LOG_FILE%"

:: Assurer le bon dossier de travail pour l'application
cd /d "%ROOT_DIR%\roms\ports\RGSX"

:: Forcer les drivers SDL côté Windows et réduire le bruit console
set PYGAME_HIDE_SUPPORT_PROMPT=1
set SDL_VIDEODRIVER=windows
set SDL_AUDIODRIVER=directsound
echo [%DATE% %TIME%] CWD before launch: %CD% >> "%LOG_FILE%"

:: Lancer l'application dans la même console et attendre sa fin
:: Forcer python.exe pour capturer la sortie
set "PY_MAIN_EXE=!PYTHON_EXE_FULL!"
echo [%DATE% %TIME%] Using interpreter: !PY_MAIN_EXE! >> "%LOG_FILE%"
echo [%DATE% %TIME%] Launching "!MAIN_SCRIPT!" now... >> "%LOG_FILE%"
"!PY_MAIN_EXE!" "!MAIN_SCRIPT!" >> "%LOG_FILE%" 2>&1
set EXITCODE=!ERRORLEVEL!
echo [%DATE% %TIME%] __main__.py exit code: !EXITCODE! >> "%LOG_FILE%"
if "!EXITCODE!"=="0" (
    echo Execution finished successfully.
    echo [%DATE% %TIME%] Execution of __main__.py finished successfully. >> "%LOG_FILE%"
) else (
    echo Error: Failed to execute __main__.py (code !EXITCODE!).
    echo [%DATE% %TIME%] Error: Failed to execute __main__.py with error code !EXITCODE!. >> "%LOG_FILE%"
    goto :error
)

:end
echo Task completed.
echo [%DATE% %TIME%] Task completed successfully. >> "%LOG_FILE%"
exit /b 0

:error
echo An error occurred.
echo [%DATE% %TIME%] An error occurred. >> "%LOG_FILE%"
exit /b 1