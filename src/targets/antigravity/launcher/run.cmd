@echo off
:: Template for adapter\mcp.cmd and bin\mindslice.cmd, filled in by build/build.py, which drops these "::" lines.
:: @ENTRY@ is entry.py relative to this script's directory, @ARGS@ the arguments.
rem MindSlice plugin launcher: runs the plugin's entry.py with the py launcher, else python.
where py >nul 2>nul || goto python
py "%~dp0@ENTRY@" @ARGS@
exit /b %ERRORLEVEL%
:python
python "%~dp0@ENTRY@" @ARGS@
exit /b %ERRORLEVEL%
