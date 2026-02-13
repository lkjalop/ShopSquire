@echo off
python -c "import importlib; importlib.import_module('src.app.routers.admin'); importlib.import_module('src.app.routers.decisions'); print('success')"
if %ERRORLEVEL% neq 0 pause
