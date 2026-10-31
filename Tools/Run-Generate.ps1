param([string]$EngineRoot, [string]$Destination)
$ErrorActionPreference='Stop'
$studyRoot = Split-Path -Parent $PSScriptRoot
if (-not $EngineRoot) { $EngineRoot=[Environment]::GetEnvironmentVariable('UE_ROOT') }
if (-not $EngineRoot) {
  $launcher='C:/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat'
  if (Test-Path -LiteralPath $launcher) {
    $found=(Get-Content -LiteralPath $launcher -Raw | ConvertFrom-Json).InstallationList | Where-Object { $_.AppName -eq 'UE_5.8' } | Select-Object -First 1
    if ($found) { $EngineRoot=$found.InstallLocation }
  }
}
if (-not $EngineRoot) { throw 'Pass -EngineRoot or set UE_ROOT to an Unreal Engine 5.8 installation.' }
$editor=Join-Path $EngineRoot 'Engine/Binaries/Win64/UnrealEditor.exe'
if (-not (Test-Path -LiteralPath $editor)) { throw 'UnrealEditor.exe was not found.' }
if (-not $Destination) { $Destination=Join-Path $studyRoot ('Sandboxes/FogboundStudy_'+(Get-Date -Format 'yyyyMMdd_HHmmss')) }
$Destination=[IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $Destination) { throw 'Destination already exists. Choose a NEW folder; existing work will not be overwritten.' }
New-Item -ItemType Directory -Path $Destination | Out-Null
Copy-Item -LiteralPath (Join-Path $studyRoot 'Fogbound/Config') -Destination (Join-Path $Destination 'Config') -Recurse
Copy-Item -LiteralPath (Join-Path $studyRoot 'Fogbound/Fogbound.uproject') -Destination (Join-Path $Destination 'Fogbound.uproject')
$project=Join-Path $Destination 'Fogbound.uproject'
$script=Join-Path $PSScriptRoot 'generate_blueprints.py'
$args=@(('"'+$project+'"'),'/Engine/Maps/Entry',('-ExecutePythonScript="'+$script+'"'),'-unattended','-NullRHI','-nosplash','-NoSound')
$process=Start-Process -FilePath $editor -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
$report=Join-Path $Destination 'Saved/StudyReports/blueprint_generation.json'
if (-not (Test-Path -LiteralPath $report)) { throw 'No generation report. See the sandbox Saved/Logs folder.' }
$generation=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $generation.success) { throw ('Blueprint generation failed: '+$generation.fatal) }
Write-Output ('Generated project: '+$project)
& (Join-Path $PSScriptRoot 'Run-Verify.ps1') -EngineRoot $EngineRoot -Project $project
