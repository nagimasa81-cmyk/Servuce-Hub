InSightec Service Hub Upgrade

Normal user flow:
1. Open Update.
2. Click Install Update.
3. Select an Upgrade ZIP.
4. Confirm.
5. The Hub shows an Updating window, creates a backup, stages files, applies the update, and restarts.

Advanced mode:
- Click Advanced.
- Enter developer password: 5963
- Rollback, open update/backups/logs/workspace folders, or run legacy update BAT.

Recommended Upgrade ZIP structure:
upgrade_manifest.json
InSightecServiceHub.py / Hub.exe
language/
help/
resources/
config.json
