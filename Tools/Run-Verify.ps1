param([string]$EngineRoot, [string]$Project)
$ErrorActionPreference='Stop'
if (-not $EngineRoot) { $EngineRoot=[Environment]::GetEnvironmentVariable('UE_ROOT') }
if (-not $EngineRoot) {
  $launcher='C:/ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat'
  if (Test-Path -LiteralPath $launcher) {
    $found=(Get-Content -LiteralPath $launcher -Raw | ConvertFrom-Json).InstallationList | Where-Object { $_.AppName -eq 'UE_5.8' } | Select-Object -First 1
    if ($found) { $EngineRoot=$found.InstallLocation }
  }
}
if (-not $EngineRoot) { throw 'Pass -EngineRoot or set UE_ROOT.' }
if (-not $Project) { $Project=Join-Path (Split-Path -Parent $PSScriptRoot) 'Fogbound/Fogbound.uproject' }
$Project=(Resolve-Path -LiteralPath $Project).ProviderPath
$editor=Join-Path $EngineRoot 'Engine/Binaries/Win64/UnrealEditor-Cmd.exe'
foreach ($file in @('validate_blueprints.py','test_blueprints.py','export_blueprints.py')) {
  $script=Join-Path $PSScriptRoot $file
  & $editor $Project -run=pythonscript ('-script='+$script) -unattended -NullRHI -nosplash -NoSound
  if ($LASTEXITCODE -ne 0) { throw ('Verification command failed: '+$file) }
}
$reports=Join-Path (Split-Path -Parent $Project) 'Saved/StudyReports'
$rules=Get-Content -LiteralPath (Join-Path $reports 'rules.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$assets=Get-Content -LiteralPath (Join-Path $reports 'assets.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $rules.passed) { throw 'Blueprint rule tests failed. Check rules.json.' }
foreach ($check in $assets.ui_checks.PSObject.Properties) { if ($check.Value -ne $true) { throw ('UI check failed: '+$check.Name) } }
foreach ($asset in $assets.PSObject.Properties) {
  if ($asset.Name.StartsWith('/Game') -and (-not $asset.Value.compiled -or $asset.Value.errors.Count -gt 0)) { throw ('Asset failed to compile: '+$asset.Name) }
}
Write-Output ('Verified; reports: '+$reports)
