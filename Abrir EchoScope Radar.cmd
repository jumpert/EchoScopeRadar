@echo off
setlocal
if exist "%~dp0EchoScopeRadar.exe" (
  start "" "%~dp0EchoScopeRadar.exe" %*
  exit /b 0
)
set "PACKAGED=%~dp0dist\0.5.0\EchoScopeRadar\EchoScopeRadar.exe"
if exist "%PACKAGED%" (
  start "" "%PACKAGED%" %*
  exit /b 0
)
set "INSTALLED=%~dp0.venv\Scripts\echoscope-web.exe"
if exist "%INSTALLED%" (
  start "" "%INSTALLED%" %*
  exit /b 0
)
echo Falta la instalacion inicial de EchoScope Radar. Consulta README.md.
pause
exit /b 1
