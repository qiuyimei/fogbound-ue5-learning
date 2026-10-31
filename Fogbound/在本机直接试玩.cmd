@echo off
setlocal
set "UE_EDITOR=D:\UnrealEngine\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
if not exist "%UE_EDITOR%" (
  echo Please open Fogbound.uproject with Unreal Engine 5.8.
  pause
  exit /b 1
)
start "Fogbound" "%UE_EDITOR%" "%~dp0Fogbound.uproject" -game -windowed -ResX=1440 -ResY=900 -nosplash -d3d11
