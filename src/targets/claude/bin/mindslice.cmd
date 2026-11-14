@echo off
rem MindSlice plugin CLI for cmd.exe and PowerShell (Git Bash and Claude's Bash tool use bin/mindslice).
setlocal
set "MS_ENTRY=%~dp0..\adapter\entry.py"
if defined MINDSLICE_PLUGIN_PYTHON goto custom
where py >nul 2>nul
if not errorlevel 1 goto launcher
python "%MS_ENTRY%" %*
exit /b
:custom
"%MINDSLICE_PLUGIN_PYTHON%" "%MS_ENTRY%" %*
exit /b
:launcher
py "%MS_ENTRY%" %*
exit /b
