@echo off
:: Template for adapter\mcp.cmd and bin\mindslice.cmd, filled in by build/build.py, which drops these "::" lines.
:: @ENTRY@ is entry.py relative to this script's directory, @ARGS@ the arguments.
:: py is used only when it actually starts a Python: inside Antigravity's terminal sandbox py.exe exists but
:: reports "No installed Python found!" while python works.
rem MindSlice plugin launcher: runs the plugin's entry.py with the py launcher when it works, else python.
py -c "" >nul 2>nul || goto python
py "%~dp0@ENTRY@" @ARGS@
exit /b %ERRORLEVEL%
:python
python "%~dp0@ENTRY@" @ARGS@
exit /b %ERRORLEVEL%
