@echo off
setlocal EnableDelayedExpansion
set "VERSION=1.6"
:: =============================================================================
:: RGSX Retrobat Launcher v%VERSION%
:: =============================================================================
:: Usage: "RGSX Retrobat.bat" [options]
::   --display=N    Launch on display N (0=primary, 1=secondary, etc.)
::   --windowed     Launch in windowed mode instead of fullscreen
::   --help         Show this help
:: =============================================================================

:: Configuration des couleurs (codes ANSI)
for /F "tokens=1,2 delims=#" %%a in ('"prompt #$H#$E# & echo on & for %%b in (1) do rem"') do (
    set "ESC=%%b"
)

:: Couleurs
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "CYAN=[96m"
set "RESET=[0m"
set "BOLD=[1m"

:: =============================================================================
:: Traitement des arguments
:: =============================================================================
set "DISPLAY_NUM="
set "WINDOWED_MODE="
set "CONFIG_FILE="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--help" goto :show_help
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--windowed" (
    set "WINDOWED_MODE=1"
    shift
    goto :parse_args
)
:: Check for --display=N format
echo %~1 | findstr /r "^--display=" >nul
if !ERRORLEVEL! EQU 0 (
    for /f "tokens=2 delims==" %%a in ("%~1") do set "DISPLAY_NUM=%%a"
    shift
    goto :parse_args
)
shift
goto :parse_args

:show_help
echo.
echo %ESC%%CYAN%RGSX Retrobat Launcher - Help%ESC%%RESET%
echo.
echo Usage: "RGSX Retrobat.bat" [options]
echo.
echo Options:
echo   --display=N    Launch on display N (0=primary, 1=secondary, etc.)
echo   --windowed     Launch in windowed mode instead of fullscreen
echo   --help, -h     Show this help
echo.
echo Examples:
echo   "RGSX Retrobat.bat"              Launch on primary display
echo   "RGSX Retrobat.bat" --display=1  Launch on secondary display (TV)
echo   "RGSX Retrobat.bat" --windowed   Launch in windowed mode
echo.
echo You can also create shortcuts with different display settings.
echo.
pause
exit /b 0

:args_done

:: URL de telechargement Python
set "PYTHON_ZIP_URL=https://github.com/RetroGameSets/RGSX/raw/main/windows/python.zip"

:: Obtenir le chemin du script de maniere fiable
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: Detecter le repertoire racine
for %%I in ("%SCRIPT_DIR%\..\.." ) do set "ROOT_DIR=%%~fI"

:: Configuration des logs
set "LOG_DIR=%ROOT_DIR%\roms\windows\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\Retrobat_RGSX_log.txt"
set "LOG_BACKUP=%LOG_DIR%\Retrobat_RGSX_log.old.txt"

:: Rotation des logs avec backup
if exist "%LOG_FILE%" (
    for %%A in ("%LOG_FILE%") do (
        if %%~zA GTR 100000 (
            if exist "%LOG_BACKUP%" del /q "%LOG_BACKUP%"
            move /y "%LOG_FILE%" "%LOG_BACKUP%" >nul 2>&1
            echo [%DATE% %TIME%] Log rotated - previous log saved as .old.txt > "%LOG_FILE%"
        )
    )
)

:: =============================================================================
:: Ecran d'accueil
:: =============================================================================
cls
echo.
echo %ESC%%CYAN%  ____   ____ ______  __ %ESC%%RESET%
echo %ESC%%CYAN% ^|  _ \ / ___^/ ___\ \/ / %ESC%%RESET%
echo %ESC%%CYAN% ^| ^|_) ^| ^|  _\___ \\  /  %ESC%%RESET%
echo %ESC%%CYAN% ^|  _ ^<^| ^|_^| ^|___) /  \  %ESC%%RESET%
echo %ESC%%CYAN% ^|_^| \_\\____^|____/_/\_\ %ESC%%RESET%
echo.
echo %ESC%%BOLD%  RetroBat Launcher v%VERSION%%ESC%%RESET%
echo   --------------------------------
if "!DISPLAY_NUM!" NEQ "0" (
    echo   %ESC%%CYAN%Display: !DISPLAY_NUM!%ESC%%RESET%
)
if "!WINDOWED_MODE!"=="1" (
    echo   %ESC%%CYAN%Mode: Windowed%ESC%%RESET%
)
echo.

:: Debut du log
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] RGSX Launcher v%VERSION% started >> "%LOG_FILE%"
echo [%DATE% %TIME%] Display: !DISPLAY_NUM!, Windowed: !WINDOWED_MODE! >> "%LOG_FILE%"
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"

:: Configuration des chemins
set "PYTHON_DIR=%ROOT_DIR%\system\tools\Python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "MAIN_SCRIPT=%ROOT_DIR%\roms\ports\RGSX\__main__.py"
set "ZIP_FILE=%ROOT_DIR%\roms\windows\python.zip"

:: Exporter RGSX_ROOT pour le script Python
set "RGSX_ROOT=%ROOT_DIR%"

:: Logger les chemins
echo [%DATE% %TIME%] System info: >> "%LOG_FILE%"
echo [%DATE% %TIME%]   ROOT_DIR: %ROOT_DIR% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   PYTHON_EXE: %PYTHON_EXE% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   MAIN_SCRIPT: %MAIN_SCRIPT% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   RGSX_ROOT: %RGSX_ROOT% >> "%LOG_FILE%"

:: Determiner la source Python a utiliser
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "PYTHON_SOURCE=none"
set "PYTHON_BUNDLE_EXE=%PYTHON_DIR%\python.exe"
set "PYTHON_BUNDLE_NEEDS_INSTALL=0"

:: Essayer d'abord python.exe dans le PATH, mais seulement si il fonctionne vraiment
for /f "delims=" %%I in ('where python.exe 2^>nul') do (
    set "PYTHON_CANDIDATE=%%~fI"
    if exist "!PYTHON_CANDIDATE!" (
        rem Utiliser findstr.exe explicite (System32) pour eviter le conflit
        rem avec GNU find (Git/MSYS) present dans le PATH.
        echo !PYTHON_CANDIDATE! | "%SystemRoot%\System32\findstr.exe" /I /C:"\Microsoft\WindowsApps\python.exe" >nul
        if !ERRORLEVEL! NEQ 0 (
            "!PYTHON_CANDIDATE!" --version >nul 2>&1
            if !ERRORLEVEL! EQU 0 if not defined PYTHON_EXE (
                set "PYTHON_EXE=!PYTHON_CANDIDATE!"
                set "PYTHON_ARGS="
                set "PYTHON_SOURCE=user"
            )
        )
    )
)

if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        py.exe -3 --version >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "PYTHON_EXE=py.exe"
            set "PYTHON_ARGS=-3"
            set "PYTHON_SOURCE=user"
        )
    )
)

if not defined PYTHON_EXE (
    for %%P in (
        "%ROOT_DIR%\roms\windows\python.exe"
        "%ROOT_DIR%\roms\windows\Python\python.exe"
        "%ROOT_DIR%\roms\windows\python\python.exe"
    ) do (
        if exist "%%~fP" (
            "%%~fP" --version >nul 2>&1
            if !ERRORLEVEL! EQU 0 if not defined PYTHON_EXE (
                set "PYTHON_EXE=%%~fP"
                set "PYTHON_ARGS="
                set "PYTHON_SOURCE=windows-bundle"
            )
        )
    )
)

if not defined PYTHON_EXE (
    if exist "!PYTHON_BUNDLE_EXE!" (
        "!PYTHON_BUNDLE_EXE!" --version >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            set "PYTHON_EXE=!PYTHON_BUNDLE_EXE!"
            set "PYTHON_ARGS="
            set "PYTHON_SOURCE=local-bundle"
        ) else (
            set "PYTHON_EXE=!PYTHON_BUNDLE_EXE!"
            set "PYTHON_ARGS="
            set "PYTHON_SOURCE=local-bundle"
            set "PYTHON_BUNDLE_NEEDS_INSTALL=1"
            echo [%DATE% %TIME%] Embedded Python found but unusable, reinstall required >> "%LOG_FILE%"
        )
    ) else (
        set "PYTHON_EXE=!PYTHON_BUNDLE_EXE!"
        set "PYTHON_ARGS="
        set "PYTHON_SOURCE=local-bundle"
        set "PYTHON_BUNDLE_NEEDS_INSTALL=1"
        echo [%DATE% %TIME%] Embedded Python not found, install required >> "%LOG_FILE%"
    )
)

:: Si Python utilisateur est recent, garder Python user et tenter pygame-ce en fallback
if /i "!PYTHON_SOURCE!"=="user" (
    set "PY_USER_VERSION_RAW="
    for /f "tokens=2" %%v in ('"!PYTHON_EXE!" !PYTHON_ARGS! --version 2^>^&1') do set "PY_USER_VERSION_RAW=%%v"
    if defined PY_USER_VERSION_RAW (
        for /f "tokens=1,2 delims=." %%a in ("!PY_USER_VERSION_RAW!") do (
            set "PY_USER_MAJOR=%%a"
            set "PY_USER_MINOR=%%b"
        )
        if "!PY_USER_MAJOR!"=="3" if !PY_USER_MINOR! GEQ 13 (
            echo [%DATE% %TIME%] User Python !PY_USER_VERSION_RAW! may be incompatible with pygame wheels, will try pygame-ce fallback before embedded Python >> "%LOG_FILE%"
        )
    )
)

echo [%DATE% %TIME%] Python source: !PYTHON_SOURCE! >> "%LOG_FILE%"
echo [%DATE% %TIME%] Python executable: !PYTHON_EXE! >> "%LOG_FILE%"

:: =============================================================================
:: Verification Python
:: =============================================================================
echo %ESC%%YELLOW%[1/3]%ESC%%RESET% Checking Python environment...
echo [%DATE% %TIME%] Step 1/3: Checking Python >> "%LOG_FILE%"

if /i "!PYTHON_SOURCE!"=="local-bundle" (
    if not exist "!PYTHON_EXE!" (
        set "PYTHON_DISCOVERED_EXE="
        for /f "delims=" %%F in ('dir /s /b "%PYTHON_DIR%\python.exe" 2^>nul') do if not defined PYTHON_DISCOVERED_EXE set "PYTHON_DISCOVERED_EXE=%%~fF"
        if defined PYTHON_DISCOVERED_EXE (
            set "PYTHON_EXE=!PYTHON_DISCOVERED_EXE!"
            echo [%DATE% %TIME%] Embedded Python discovered at !PYTHON_EXE! >> "%LOG_FILE%"
        )
    )
    if not exist "!PYTHON_EXE!" set "PYTHON_BUNDLE_NEEDS_INSTALL=1"
    if exist "!PYTHON_EXE!" (
        "!PYTHON_EXE!" --version >nul 2>&1
        if !ERRORLEVEL! NEQ 0 set "PYTHON_BUNDLE_NEEDS_INSTALL=1"
    )
)

if /i "!PYTHON_SOURCE!"=="local-bundle" if "!PYTHON_BUNDLE_NEEDS_INSTALL!"=="1" (
    echo       %ESC%%YELLOW%^> Embedded Python missing or broken, installing...%ESC%%RESET%
    echo [%DATE% %TIME%] Embedded Python missing/broken, starting installation >> "%LOG_FILE%"
    
    :: Creer le dossier Python
    if not exist "%PYTHON_DIR%" (
        mkdir "%PYTHON_DIR%" 2>nul
        echo [%DATE% %TIME%] Created folder: %PYTHON_DIR% >> "%LOG_FILE%"
    )
    
    :: Verifier si le ZIP existe, sinon le telecharger
    if not exist "%ZIP_FILE%" (
        echo       %ESC%%YELLOW%^> python.zip not found, downloading from GitHub...%ESC%%RESET%
        echo [%DATE% %TIME%] python.zip not found, attempting download >> "%LOG_FILE%"
        echo [%DATE% %TIME%] Download URL: %PYTHON_ZIP_URL% >> "%LOG_FILE%"
        
        :: Verifier si curl est disponible
        where curl.exe >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo       %ESC%%CYAN%^> Using curl to download...%ESC%%RESET%
            echo [%DATE% %TIME%] Using curl.exe for download >> "%LOG_FILE%"
            curl.exe -L -# -o "%ZIP_FILE%" "%PYTHON_ZIP_URL%"
            set DOWNLOAD_RESULT=!ERRORLEVEL!
        ) else (
            :: Fallback sur PowerShell
            echo       %ESC%%CYAN%^> Using PowerShell to download...%ESC%%RESET%
            echo [%DATE% %TIME%] curl not found, using PowerShell >> "%LOG_FILE%"
            powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '%PYTHON_ZIP_URL%' -OutFile '%ZIP_FILE%'"
            set DOWNLOAD_RESULT=!ERRORLEVEL!
        )
        
        :: Verifier le resultat du telechargement
        if !DOWNLOAD_RESULT! NEQ 0 (
            echo.
            echo %ESC%%RED%  ERROR: Download failed!%ESC%%RESET%
            echo.
            echo   Please download python.zip manually from:
            echo   %ESC%%CYAN%%PYTHON_ZIP_URL%%ESC%%RESET%
            echo.
            echo   And place it in:
            echo   %ESC%%CYAN%%ROOT_DIR%\roms\windows\%ESC%%RESET%
            echo.
            echo [%DATE% %TIME%] ERROR: Download failed with code !DOWNLOAD_RESULT! >> "%LOG_FILE%"
            goto :error
        )
        
        :: Verifier que le fichier a bien ete telecharge et n'est pas vide
        if not exist "%ZIP_FILE%" (
            echo.
            echo %ESC%%RED%  ERROR: Download failed - file not created!%ESC%%RESET%
            echo [%DATE% %TIME%] ERROR: ZIP file not created after download >> "%LOG_FILE%"
            goto :error
        )
        
        :: Verifier la taille du fichier (doit etre > 1MB pour etre valide)
        for %%A in ("%ZIP_FILE%") do set ZIP_SIZE=%%~zA
        if !ZIP_SIZE! LSS 1000000 (
            echo.
            echo %ESC%%RED%  ERROR: Downloaded file appears invalid ^(too small^)!%ESC%%RESET%
            echo [%DATE% %TIME%] ERROR: Downloaded file too small: !ZIP_SIZE! bytes >> "%LOG_FILE%"
            del /q "%ZIP_FILE%" 2>nul
            goto :error
        )
        
        echo       %ESC%%GREEN%^> Download complete ^(!ZIP_SIZE! bytes^)%ESC%%RESET%
        echo [%DATE% %TIME%] Download successful: !ZIP_SIZE! bytes >> "%LOG_FILE%"
    )
    
    :: Extraction avec progression simulee
    echo       %ESC%%YELLOW%^> Extracting Python...%ESC%%RESET%
    echo [%DATE% %TIME%] Extracting python.zip >> "%LOG_FILE%"
    
    <nul set /p "=       ["
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%ZIP_FILE%' -DestinationPath '%PYTHON_DIR%' -Force; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }" >>"%LOG_FILE%" 2>&1
    set TAR_RESULT=!ERRORLEVEL!
    echo %ESC%%GREEN%##########%ESC%%RESET%] Done
    
    if !TAR_RESULT! NEQ 0 (
        echo.
        echo %ESC%%RED%  ERROR: Extraction failed!%ESC%%RESET%
        echo [%DATE% %TIME%] ERROR: archive extraction failed with code !TAR_RESULT! >> "%LOG_FILE%"
        goto :error
    )
    
    echo [%DATE% %TIME%] Extraction completed >> "%LOG_FILE%"
    
    :: Supprimer ZIP
    del /q "%ZIP_FILE%" 2>nul
    echo       %ESC%%GREEN%^> python.zip cleaned up%ESC%%RESET%
    echo [%DATE% %TIME%] python.zip deleted >> "%LOG_FILE%"
    
    :: Verifier installation
    if not exist "%PYTHON_EXE%" (
        set "PYTHON_DISCOVERED_EXE="
        for /f "delims=" %%F in ('dir /s /b "%PYTHON_DIR%\python.exe" 2^>nul') do if not defined PYTHON_DISCOVERED_EXE set "PYTHON_DISCOVERED_EXE=%%~fF"
        if defined PYTHON_DISCOVERED_EXE (
            set "PYTHON_EXE=!PYTHON_DISCOVERED_EXE!"
            echo [%DATE% %TIME%] Embedded Python discovered after extraction at !PYTHON_EXE! >> "%LOG_FILE%"
        )
    )

    if not exist "!PYTHON_EXE!" (
        echo.
        echo %ESC%%RED%  ERROR: Python not found after extraction!%ESC%%RESET%
        echo [%DATE% %TIME%] ERROR: python.exe not found after extraction in %PYTHON_DIR% >> "%LOG_FILE%"
        goto :error
    )
)

if not defined PYTHON_EXE (
    echo.
    echo %ESC%%RED%  ERROR: No usable Python interpreter found!%ESC%%RESET%
    echo [%DATE% %TIME%] ERROR: PYTHON_EXE not defined after detection/install >> "%LOG_FILE%"
    goto :error
)

"!PYTHON_EXE!" !PYTHON_ARGS! --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo %ESC%%RED%  ERROR: Selected Python is not executable!%ESC%%RESET%
    echo [%DATE% %TIME%] ERROR: Python executable test failed for !PYTHON_EXE! !PYTHON_ARGS! >> "%LOG_FILE%"
    goto :error
)

:: Afficher et logger la version Python
for /f "tokens=*" %%v in ('"!PYTHON_EXE!" !PYTHON_ARGS! --version 2^>^&1') do set "PYTHON_VERSION=%%v"
echo       %ESC%%GREEN%^> !PYTHON_VERSION! found via !PYTHON_SOURCE!%ESC%%RESET%
echo [%DATE% %TIME%] !PYTHON_VERSION! detected using !PYTHON_SOURCE! >> "%LOG_FILE%"

:: Verifier et installer les dependances Python si necessaires
set "MISSING_PACKAGES="
echo [%DATE% %TIME%] Checking Python modules: requests and pygame >> "%LOG_FILE%"
set "MODULE_CHECK_TMP=%TEMP%\rgsx_py_mod_check_!RANDOM!!RANDOM!.txt"
"!PYTHON_EXE!" !PYTHON_ARGS! -c "import importlib.util,sys;mods=['requests','pygame'];missing=[m for m in mods if importlib.util.find_spec(m) is None];sys.stdout.write(' '.join(missing))" > "!MODULE_CHECK_TMP!" 2>&1
set "MODULE_CHECK_RESULT=!ERRORLEVEL!"
if !MODULE_CHECK_RESULT! NEQ 0 (
    echo.
    echo %ESC%%RED%  ERROR: Python module check failed!%ESC%%RESET%
    echo [%DATE% %TIME%] ERROR: Module check failed with code !MODULE_CHECK_RESULT! >> "%LOG_FILE%"
    type "!MODULE_CHECK_TMP!" >> "%LOG_FILE%"
    del /q "!MODULE_CHECK_TMP!" 2>nul
    goto :error
)

set /p "MISSING_PACKAGES=" < "!MODULE_CHECK_TMP!"
del /q "!MODULE_CHECK_TMP!" 2>nul

if defined MISSING_PACKAGES (
    echo [%DATE% %TIME%] Missing Python modules detected: !MISSING_PACKAGES! >> "%LOG_FILE%"
) else (
    echo [%DATE% %TIME%] All required Python modules already present >> "%LOG_FILE%"
)

if defined MISSING_PACKAGES (
    echo       %ESC%%YELLOW%^> Installing Python packages: !MISSING_PACKAGES!%ESC%%RESET%
    echo [%DATE% %TIME%] Installing missing packages: !MISSING_PACKAGES! >> "%LOG_FILE%"

    "!PYTHON_EXE!" !PYTHON_ARGS! -m pip --version >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [%DATE% %TIME%] pip missing, trying ensurepip >> "%LOG_FILE%"
        "!PYTHON_EXE!" !PYTHON_ARGS! -m ensurepip --upgrade >> "%LOG_FILE%" 2>&1
    )

    set "PIP_USER_FLAG="
    if /i "!PYTHON_SOURCE!"=="user" set "PIP_USER_FLAG=--user"

    set "MISSING_PYGAME="
    set "MISSING_OTHER_PACKAGES="
    for %%p in (!MISSING_PACKAGES!) do (
        if /i "%%p"=="pygame" (
            set "MISSING_PYGAME=1"
        ) else (
            if defined MISSING_OTHER_PACKAGES (
                set "MISSING_OTHER_PACKAGES=!MISSING_OTHER_PACKAGES! %%p"
            ) else (
                set "MISSING_OTHER_PACKAGES=%%p"
            )
        )
    )

    if defined MISSING_OTHER_PACKAGES (
        "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install !PIP_USER_FLAG! !MISSING_OTHER_PACKAGES! >> "%LOG_FILE%" 2>&1
        set "PIP_RESULT=!ERRORLEVEL!"
        if !PIP_RESULT! NEQ 0 (
            echo.
            echo %ESC%%RED%  ERROR: Failed to install Python dependencies: !MISSING_OTHER_PACKAGES!%ESC%%RESET%
            echo [%DATE% %TIME%] ERROR: pip install failed for !MISSING_OTHER_PACKAGES! with code !PIP_RESULT! >> "%LOG_FILE%"
            goto :error
        )
    )

    if defined MISSING_PYGAME (
        echo [%DATE% %TIME%] Installing pygame with binary wheel only >> "%LOG_FILE%"
        "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install !PIP_USER_FLAG! --only-binary pygame pygame >> "%LOG_FILE%" 2>&1
        set "PIP_RESULT=!ERRORLEVEL!"
        if !PIP_RESULT! NEQ 0 (
            if /i "!PYTHON_SOURCE!"=="user" (
                echo [%DATE% %TIME%] pygame wheel install failed on user Python, trying pygame-ce fallback >> "%LOG_FILE%"
                "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install !PIP_USER_FLAG! pygame-ce >> "%LOG_FILE%" 2>&1
                set "PIP_RESULT=!ERRORLEVEL!"
                if !PIP_RESULT! EQU 0 (
                    "!PYTHON_EXE!" !PYTHON_ARGS! -c "import pygame" >nul 2>&1
                    set "PIP_RESULT=!ERRORLEVEL!"
                )
                if !PIP_RESULT! NEQ 0 (
                    echo [%DATE% %TIME%] pygame-ce fallback failed on user Python, will require embedded Python >> "%LOG_FILE%"
                    set "PYTHON_EXE=!PYTHON_BUNDLE_EXE!"
                    set "PYTHON_ARGS="
                    set "PYTHON_SOURCE=local-bundle"
                    set "PYTHON_BUNDLE_NEEDS_INSTALL=1"
                    goto :error
                )
                echo [%DATE% %TIME%] pygame-ce installed successfully on user Python >> "%LOG_FILE%"
            ) else (
                echo.
                echo %ESC%%RED%  ERROR: Failed to install pygame binary wheel!%ESC%%RESET%
                echo [%DATE% %TIME%] ERROR: pygame wheel install failed with code !PIP_RESULT! >> "%LOG_FILE%"
                echo [%DATE% %TIME%] ERROR: Try embedded Python bundle or Python 3.12/3.11 for pygame compatibility >> "%LOG_FILE%"
                goto :error
            )
        )
    )

    echo       %ESC%%GREEN%^> Python dependencies installed%ESC%%RESET%
    echo [%DATE% %TIME%] Python dependencies installed successfully >> "%LOG_FILE%"
) else (
    echo       %ESC%%GREEN%^> Python dependencies OK%ESC%%RESET%
    echo [%DATE% %TIME%] Python dependencies already available >> "%LOG_FILE%"
)

:: =============================================================================
:: Configuration automatique du pare-feu Windows (une seule fois, transparente)
:: =============================================================================
:: Ajoute des regles entrantes pour le binaire qBittorrent integre et pour le
:: port TCP 18572 de la WebUI, afin que le debug LAN fonctionne des le premier
:: lancement manuel. Peut demander une elevation UAC une seule fois (marqueur
:: ecrit dans tous les cas pour ne jamais redemander a chaque lancement).
set "QBITTORRENT_EXE=%ROOT_DIR%\saves\ports\rgsx\qbittorrent-portable\qbittorrent-portable.exe"
set "FIREWALL_SCRIPT=%ROOT_DIR%\roms\windows\scripts\rgsx_firewall_setup.ps1"
set "FIREWALL_MARKER_DIR=%ROOT_DIR%\saves\ports\rgsx"
set "FIREWALL_MARKER=%FIREWALL_MARKER_DIR%\.firewall_rules_configured"

if not exist "%FIREWALL_MARKER%" (
    if exist "%FIREWALL_SCRIPT%" (
        echo       %ESC%%YELLOW%^> Configuring Windows Firewall for downloads ^(one-time, background^)...%ESC%%RESET%
        if not exist "%FIREWALL_MARKER_DIR%" mkdir "%FIREWALL_MARKER_DIR%" 2>nul
        echo [%DATE% %TIME%] Firewall setup attempted >> "%FIREWALL_MARKER%" 2>nul
        echo [%DATE% %TIME%] One-time firewall setup: launching %FIREWALL_SCRIPT% detached/hidden in background >> "%LOG_FILE%"
        start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%FIREWALL_SCRIPT%" -QbittorrentPath "%QBITTORRENT_EXE%" -WebUiPort 18572 -LogFile "%LOG_FILE%" >nul 2>&1
    ) else (
        echo [%DATE% %TIME%] Firewall setup script not found, skipping >> "%LOG_FILE%"
    )
) else (
    echo [%DATE% %TIME%] Firewall already configured previously, skipping >> "%LOG_FILE%"
)

:: =============================================================================
:: Verification script principal
:: =============================================================================
echo %ESC%%YELLOW%[2/3]%ESC%%RESET% Checking RGSX application...
echo [%DATE% %TIME%] Step 2/3: Checking RGSX files >> "%LOG_FILE%"

if not exist "%MAIN_SCRIPT%" (
    echo.
    echo %ESC%%RED%  ERROR: __main__.py not found!%ESC%%RESET%
    echo.
    echo   Expected location:
    echo   %ESC%%CYAN%%MAIN_SCRIPT%%ESC%%RESET%
    echo.
    echo [%DATE% %TIME%] ERROR: __main__.py not found at %MAIN_SCRIPT% >> "%LOG_FILE%"
    goto :error
)

echo       %ESC%%GREEN%^> RGSX files OK%ESC%%RESET%
echo [%DATE% %TIME%] RGSX files verified >> "%LOG_FILE%"

:: =============================================================================
:: Lancement
:: =============================================================================
echo %ESC%%YELLOW%[3/3]%ESC%%RESET% Launching RGSX...
echo [%DATE% %TIME%] Step 3/3: Launching application >> "%LOG_FILE%"

:: Changer le repertoire de travail
cd /d "%ROOT_DIR%\roms\ports\RGSX"
echo [%DATE% %TIME%] Working directory: %CD% >> "%LOG_FILE%"

:: Configuration SDL/Pygame
set PYGAME_HIDE_SUPPORT_PROMPT=1
set SDL_VIDEODRIVER=windows
set SDL_AUDIODRIVER=directsound
set PYTHONWARNINGS=ignore::UserWarning:pygame.pkgdata
set PYTHONIOENCODING=utf-8

:: =============================================================================
:: Configuration multi-ecran
:: =============================================================================
:: SDL_VIDEO_FULLSCREEN_HEAD: Selectionne l'ecran pour le mode plein ecran
:: 0 = ecran principal, 1 = ecran secondaire, etc.
:: Ces variables ne sont definies que si --display=N ou --windowed est passe
:: Sinon, le script Python utilisera les parametres de rgsx_settings.json

echo [%DATE% %TIME%] Display configuration: >> "%LOG_FILE%"
if defined DISPLAY_NUM (
    set SDL_VIDEO_FULLSCREEN_HEAD=!DISPLAY_NUM!
    set RGSX_DISPLAY=!DISPLAY_NUM!
    echo [%DATE% %TIME%]   SDL_VIDEO_FULLSCREEN_HEAD=!DISPLAY_NUM! ^(from --display arg^) >> "%LOG_FILE%"
    echo [%DATE% %TIME%]   RGSX_DISPLAY=!DISPLAY_NUM! ^(from --display arg^) >> "%LOG_FILE%"
) else (
    echo [%DATE% %TIME%]   Display: using rgsx_settings.json config >> "%LOG_FILE%"
)
if defined WINDOWED_MODE (
    set RGSX_WINDOWED=!WINDOWED_MODE!
    echo [%DATE% %TIME%]   RGSX_WINDOWED=!WINDOWED_MODE! ^(from --windowed arg^) >> "%LOG_FILE%"
) else (
    echo [%DATE% %TIME%]   Windowed: using rgsx_settings.json config >> "%LOG_FILE%"
)

:: Log environnement
echo [%DATE% %TIME%] Environment variables set: >> "%LOG_FILE%"
echo [%DATE% %TIME%]   RGSX_ROOT=%RGSX_ROOT% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   SDL_VIDEODRIVER=%SDL_VIDEODRIVER% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   SDL_AUDIODRIVER=%SDL_AUDIODRIVER% >> "%LOG_FILE%"
echo [%DATE% %TIME%]   PYTHONIOENCODING=%PYTHONIOENCODING% >> "%LOG_FILE%"

echo.
if defined DISPLAY_NUM (
    echo   %ESC%%CYAN%Launching on display !DISPLAY_NUM!...%ESC%%RESET%
)
if defined WINDOWED_MODE (
    echo   %ESC%%CYAN%Windowed mode enabled%ESC%%RESET%
)
echo   %ESC%%CYAN%Starting RGSX application...%ESC%%RESET%
echo   %ESC%%BOLD%Press Ctrl+C to force quit if needed%ESC%%RESET%
echo.
echo [%DATE% %TIME%] Executing: "!PYTHON_EXE!" !PYTHON_ARGS! "%MAIN_SCRIPT%" >> "%LOG_FILE%"
echo [%DATE% %TIME%] --- Application output start --- >> "%LOG_FILE%"

"!PYTHON_EXE!" !PYTHON_ARGS! "%MAIN_SCRIPT%" >> "%LOG_FILE%" 2>&1
set EXITCODE=!ERRORLEVEL!

echo [%DATE% %TIME%] --- Application output end --- >> "%LOG_FILE%"
echo [%DATE% %TIME%] Exit code: !EXITCODE! >> "%LOG_FILE%"

if "!EXITCODE!"=="0" (
    echo.
    echo   %ESC%%GREEN%RGSX closed successfully.%ESC%%RESET%
    echo.
    echo [%DATE% %TIME%] Application closed successfully >> "%LOG_FILE%") else if "!EXITCODE!"=="1" (
    echo.
    echo   %ESC%%GREEN%RGSX closed normally.%ESC%%RESET%
    echo.
    >> "%LOG_FILE%" echo [%DATE% %TIME%] Application closed normally >> "%LOG_FILE%"
    goto :end) else (
    echo.
    echo   %ESC%%RED%RGSX exited with error code !EXITCODE!%ESC%%RESET%
    echo.
    echo [%DATE% %TIME%] ERROR: Application exited with code !EXITCODE! >> "%LOG_FILE%"
    goto :error
)

:end
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] Session ended normally >> "%LOG_FILE%"
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"
ping -n 1 -w 5000 127.255.255.255 >nul
exit /b 0

:error
echo.
echo   %ESC%%RED%An error occurred. Check the log file:%ESC%%RESET%
echo   %ESC%%CYAN%%LOG_FILE%%ESC%%RESET%
echo.
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] Session ended with errors >> "%LOG_FILE%"
echo [%DATE% %TIME%] ========================================== >> "%LOG_FILE%"
echo.
echo   Press any key to close...
pause >nul
exit /b 1