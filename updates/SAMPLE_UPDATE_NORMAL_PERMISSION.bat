@echo off
rem InSightec Service Hub sample update.
rem Normal user permission only. No admin/UAC elevation.
cd /d "%~dp0\.."
if not exist logs mkdir logs
echo Update started: %date% %time% >> logs\update_sample.log
echo Put replacement files here and use copy /Y commands. >> logs\update_sample.log
echo Example: copy /Y new_config.json config.json >> logs\update_sample.log
echo Complete. >> logs\update_sample.log
pause
