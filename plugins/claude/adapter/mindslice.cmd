@echo off
rem MindSlice plugin CLI for cmd.exe and PowerShell (Git Bash and Claude's Bash tool use adapter/mindslice).
rem Python: %MINDSLICE_PLUGIN_PYTHON%, else the py launcher, else python. entry.py upgrades to 3.12+ itself.
setlocal
set "MS_ENTRY=%~dp0entry.py"
set "MS_PY=%MINDSLICE_PLUGIN_PYTHON%"
if not defined MS_PY (
  where py >nul 2>nul && set "MS_PY=py" || set "MS_PY=python"
)
"%MS_PY%" "%MS_ENTRY%" %*
rem Explicit code: a bare "exit /b" loses a failing exit code when the script runs as a process (cmd /c).
exit /b %ERRORLEVEL%
