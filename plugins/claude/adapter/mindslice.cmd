@echo off
rem MindSlice plugin launcher for Windows (adapter\mindslice.cmd). Claude starts the MCP server as
rem ${CLAUDE_PLUGIN_ROOT}/adapter/mindslice, which resolves to this file there (PATHEXT); the hooks use the sh one.
rem Plain on purpose, like adapter/mindslice: the path it runs is %CLAUDE_PLUGIN_ROOT%\adapter\entry.py, the
rem interpreter the py launcher, else python. entry.py upgrades to Python 3.12+ itself.
setlocal
if not defined CLAUDE_PLUGIN_ROOT (
  echo mindslice plugin: CLAUDE_PLUGIN_ROOT is not set ^(run the mindslice command instead^) 1>&2
  exit /b 1
)
where py >nul 2>nul || goto python
py "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" %*
rem Explicit code: a bare "exit /b" loses a failing exit code when the script runs as a process (cmd /c).
exit /b %ERRORLEVEL%
:python
python "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" %*
exit /b %ERRORLEVEL%
