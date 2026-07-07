Place extracted tool EXE files into these folders:

- tools\DOanalysis-a\DO Analysis Qt.exe
- tools\DOanalysis-b\DO Analysis Qt Ver1.0.1.exe
- tools\LogExplorer\LogMergeTool_NoExcel.exe
- tools\TrackerSNR\TrackerSNR_CLEAN_EXE.exe
- tools\VIMeasure\VIMeasureAnalyzer.exe

This source-only package does not include the large EXE packages.
The Hub reads config.json and launches the configured EXE path.


MODULE VERSION CHANGE
=====================
Each module owns its version in its own manifest.json.
To change a module version, edit:

  tools/<ModuleFolder>/manifest.json

Example:
  "version": "1.0.1"

After editing manifest.json, restart the Hub or press Refresh on the Tools page.
The Tool card will show the updated version and "Version source: manifest.json".

繁體中文：模組版本由各模組的 manifest.json 管理。要變更版本，請修改 version 欄位後重新啟動 Hub 或按 Refresh。
