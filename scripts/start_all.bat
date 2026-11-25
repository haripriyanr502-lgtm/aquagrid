@echo off
REM Opens one window per AquaGrid service. Run from the scripts folder after setup.
REM Add  --simulate  to the bridge line below if the Arduino is not connected.
cd /d %~dp0
start "simulator"        cmd /k ".venv\Scripts\activate && python simulator.py"
timeout /t 5 >nul
start "bridge"           cmd /k ".venv\Scripts\activate && python bridge.py"
start "brain (twin)"     cmd /k ".venv\Scripts\activate && python brain.py"
start "alerts"           cmd /k ".venv\Scripts\activate && python alerts.py"
start "road risk"        cmd /k ".venv\Scripts\activate && python road_risk.py"
start "repair priority"  cmd /k ".venv\Scripts\activate && python repair_priority.py"
start "drainx worker"    cmd /k ".venv\Scripts\activate && python pothole_detect.py --worker"
echo All services started. Close a window to stop that service.
