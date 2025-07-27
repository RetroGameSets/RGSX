@echo off
setlocal EnableDelayedExpansion

:: Vérifier si Python est installé
echo Vérification de la présence de Python...
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Python est déjà installé.
    python --version
    goto :end
)

:: Python non trouvé, procéder au téléchargement
echo Python non trouvé. Téléchargement en cours...
set PYTHON_VERSION=3.13.5
set PYTHON_INSTALLER=python-%PYTHON_VERSION%-amd64.exe
set DOWNLOAD_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_INSTALLER%

:: Créer un dossier temporaire
set TEMP_DIR=%TEMP%\PythonInstall
mkdir "%TEMP_DIR%"

:: Télécharger l'installateur
echo Téléchargement de Python %PYTHON_VERSION%...
powershell -Command "Invoke-WebRequest -Uri %DOWNLOAD_URL% -OutFile %TEMP_DIR%\%PYTHON_INSTALLER%"

:: Vérifier si le téléchargement a réussi
if not exist "%TEMP_DIR%\%PYTHON_INSTALLER%" (
    echo Erreur : Échec du téléchargement de l'installateur.
    goto :error
)

:: Installer Python
echo Installation de Python...
start /wait "" "%TEMP_DIR%\%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0

:: Vérifier si l'installation a réussi
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Python a été installé avec succès.
    python --version
) else (
    echo Erreur : L'installation de Python a échoué.
    goto :error
)

:: Nettoyage
echo Nettoyage des fichiers temporaires...
rd /s /q "%TEMP_DIR%"

:end
echo Script terminé. Lancement de RGSX
python __main__.py
pause
exit /b 0

:error
echo Une erreur s'est produite.
rd /s /q "%TEMP_DIR%"
pause
exit /b 1