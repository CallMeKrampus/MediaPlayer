@echo off
setlocal
cd /d "%~dp0"
set PATH=%~dp0lib;%PATH%
python boob_player.py %*
endlocal
