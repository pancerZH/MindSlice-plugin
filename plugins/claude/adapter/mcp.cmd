@echo off
where py 1>&2 || goto python
py "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" mcp
goto :eof
:python
python "%CLAUDE_PLUGIN_ROOT%\adapter\entry.py" mcp
