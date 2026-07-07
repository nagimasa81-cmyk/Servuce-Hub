
@echo off
setlocal

cd /d "%~dp0"

echo =====================================
echo Building InSightecServiceHub
echo =====================================

python -m pip install --upgrade pip
python -m pip install pyinstaller pywin32

if errorlevel 1 (
    echo [ERROR] Failed to install required packages.
    exit /b 1
)

pyinstaller ^
  --noconfirm ^
  --windowed ^
  --name InSightecServiceHub ^
  --add-data "config.json;." ^
  --add-data "language;language" ^
  --add-data "help;help" ^
  InSightecServiceHub.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

if exist "dist\InSightecServiceHub\InSightecServiceHub.exe" (

    if exist "config.json" (
        copy /Y config.json dist\InSightecServiceHub\config.json
    )

    if exist "tools" (
        xcopy /E /I /Y tools dist\InSightecServiceHub\tools
    )

    if exist "plugins" (
        xcopy /E /I /Y plugins dist\InSightecServiceHub\plugins
    )

    if exist "database" (
        xcopy /E /I /Y database dist\InSightecServiceHub\database
    )

    if exist "language" (
        xcopy /E /I /Y language dist\InSightecServiceHub\language
    )

    if exist "help" (
        xcopy /E /I /Y help dist\InSightecServiceHub\help
    )

    if exist "updates" (
        xcopy /E /I /Y updates dist\InSightecServiceHub\updates
    )

    if exist "resources" (
        xcopy /E /I /Y resources dist\InSightecServiceHub\resources
    )

) else (
    echo [ERROR] EXE was not created.
    exit /b 1
)

echo.
echo =====================================
echo Build completed successfully
echo Output:
echo dist\InSightecServiceHub
echo =====================================
echo.

if not defined GITHUB_ACTIONS pause

exit /b 0
