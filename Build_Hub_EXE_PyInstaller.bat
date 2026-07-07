@echo off
cd /d "%~dp0"
python -m pip install pyinstaller pywin32
pyinstaller --noconfirm --windowed --name InSightecServiceHub --add-data "config.json;." --add-data "language;language" --add-data "help;help" InSightecServiceHub.py
if exist dist\InSightecServiceHub\InSightecServiceHub.exe (
  copy /Y config.json dist\InSightecServiceHub\config.json
  xcopy /E /I /Y tools dist\InSightecServiceHub\tools
  xcopy /E /I /Y plugins dist\InSightecServiceHub\plugins
  xcopy /E /I /Y database dist\InSightecServiceHub\database
  xcopy /E /I /Y language dist\InSightecServiceHub\language
  xcopy /E /I /Y help dist\InSightecServiceHub\help
  xcopy /E /I /Y updates dist\InSightecServiceHub\updates
  xcopy /E /I /Y resources dist\InSightecServiceHub\resources
)
pause
