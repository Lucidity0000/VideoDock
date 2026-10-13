$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$localPython = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $localPython)) {
    throw 'Run setup.ps1 first, or install VideoDock from the Windows installer.'
}
Start-Process -FilePath $localPython -ArgumentList ('"{0}"' -f (Join-Path $projectRoot 'run_videodock.py')) -WorkingDirectory $projectRoot -WindowStyle Hidden

