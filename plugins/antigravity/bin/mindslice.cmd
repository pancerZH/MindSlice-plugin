@echo off
rem MindSlice plugin launcher: runs the plugin's entry.py with the py launcher, else python.
where py >nul 2>nul || goto python
py "%~dp0..\adapter\entry.py" %*
exit /b %ERRORLEVEL%
:python
python "%~dp0..\adapter\entry.py" %*
exit /b %ERRORLEVEL%
