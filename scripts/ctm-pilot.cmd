@echo off
rem CTM pilot: local page at http://127.0.0.1:8765/ ; CTM decides each work's working directory
rem --root: the CTM directory (memory, records, executor sessions, scratch work); required for now
rem usage: ctm-pilot.cmd --root <CTM directory> [--open] [--port 8765]
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"
python -m context_tree.pilot %*
