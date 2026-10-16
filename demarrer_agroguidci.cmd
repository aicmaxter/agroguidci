@echo off
REM Lanceur AGROGUIDCI (voir demarrer_agroguidci.py).
REM   demarrer_agroguidci.cmd            : orchestrateur + 4 agents
REM   demarrer_agroguidci.cmd --arreter  : stoppe les agents
cd /d "%~dp0"
python demarrer_agroguidci.py %*
