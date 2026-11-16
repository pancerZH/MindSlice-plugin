@echo off
rem MindSlice plugin launcher: runs the plugin's entry.py with the py launcher when it works, else python.
py -c "" >nul 2>nul || goto python
py "%~dp0entry.py" mcp
exit /b %ERRORLEVEL%
:python
python "%~dp0entry.py" mcp
exit /b %ERRORLEVEL%
