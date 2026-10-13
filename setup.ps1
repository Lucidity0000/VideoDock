param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. Pass its executable using -Python.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install --index-url https://pypi.org/simple --no-input --keyring-provider disabled --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & '.\.venv\Scripts\python.exe' tools/fetch_dependencies.py
    if ($LASTEXITCODE -ne 0) { throw 'Verified tool installation failed.' }
    & '.\.venv\Scripts\python.exe' tools/setup_inference.py
    if ($LASTEXITCODE -ne 0) { throw 'Verified local inference runtime installation failed.' }
    Write-Output 'Ready. Run .\start.ps1 to open VideoDock.'
} finally {
    Pop-Location
}

