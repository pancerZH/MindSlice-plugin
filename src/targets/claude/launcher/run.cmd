@echo off
:: Template for adapter\mcp.cmd (Claude starts adapter/mcp, which resolves to it on Windows through PATHEXT),
:: filled in by build/build.py, which drops these "::" lines. Only CLAUDE_PLUGIN_ROOT, no nul, no ERRORLEVEL.
where py 1>&2 || goto python
py "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" @ARGS@
goto :eof
:python
python "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" @ARGS@
