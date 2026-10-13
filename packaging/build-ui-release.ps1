param([string]$Python = '', [switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
Push-Location $projectRoot
try {
    $releaseVersion = (& $Python -c "import videodock; print(videodock.__version__)").Trim()
    if ($releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a numeric release version.' }
    $releaseFolder = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist\VideoDock-$releaseVersion"))
    $distRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist')) + '\'
    if (-not $releaseFolder.StartsWith($distRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The release target must stay inside the workspace dist folder.'
    }
    $workerPath = [IO.Path]::GetFullPath((Join-Path $projectRoot 'vendor\VideoDockWorker.exe'))
    $runningCopies = Get-Process | Where-Object {
        try { $_.Path -and ($_.Path.StartsWith($releaseFolder + '\', [StringComparison]::OrdinalIgnoreCase) -or $_.Path -eq $workerPath) }
        catch { $false }
    }
    if ($runningCopies) { throw 'A target release or source worker is running. Finish it before rebuilding.' }
    if (-not (Test-Path -LiteralPath 'vendor\inference\VideoDockInferenceWorker.exe')) {
        throw 'The verified frozen inference runtime is required; use build.ps1 for a complete runtime build.'
    }
    # Only changed Python worker/GUI code is rebuilt. Native inference assets are retained.
    $catalogData = (Join-Path $projectRoot 'videodock\model_catalog.json') + ';videodock'
    & $Python -m PyInstaller --noconfirm --clean --onefile --console --name VideoDockWorker --distpath build/worker --workpath build/worker-temp --specpath build --exclude-module PySide6 --exclude-module yt_dlp --exclude-module torch --exclude-module transformers --exclude-module transcribe_cpp --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all tokenizers --collect-all av --collect-all sentencepiece --collect-all opencc --add-data $catalogData run_worker.py
    if ($LASTEXITCODE -ne 0) { throw 'Worker build failed.' }
    Copy-Item -LiteralPath 'build\worker\VideoDockWorker.exe' -Destination 'vendor\VideoDockWorker.exe'
    & $Python -m PyInstaller --noconfirm --clean packaging/VideoDock.spec
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
    if (-not $SkipInstaller) {
        & (Join-Path $projectRoot 'build\inno\ISCC.exe') packaging/VideoDock.iss
        if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    }
} finally {
    Pop-Location
}
