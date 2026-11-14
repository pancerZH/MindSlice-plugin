@echo off
rem MindSlice plugin launcher: runs the plugin's entry.py with the py launcher, else python.
where py >nul 2>nul || goto python
py "%~dp0entry.py" mcp
exit /b %ERRORLEVEL%
:python
python "%~dp0entry.py" mcp
exit /b %ERRORLEVEL%
