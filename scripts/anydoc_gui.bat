@echo off
REM Lanza la GUI de anydoc con doble clic (usa pythonw para no abrir consola).
setlocal
set "SCRIPT_DIR=%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%SCRIPT_DIR%anydoc_gui.py"
) else (
    start "" python "%SCRIPT_DIR%anydoc_gui.py"
)
