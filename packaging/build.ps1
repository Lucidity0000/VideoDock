param([string]$Python = '', [string]$ISCC = '', [switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
Push-Location $projectRoot
try {
    $releaseVersion = (& $Python -c "import videodock; print(videodock.__version__)").Trim()
    $releaseFolder = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist\VideoDock-$releaseVersion"))
    foreach ($target in @($releaseFolder, (Join-Path $projectRoot "dist\VideoDock-Setup-$releaseVersion.exe"),
                          (Join-Path $projectRoot "dist\VideoDock-$releaseVersion-SHA256SUMS.txt"),
                          (Join-Path $projectRoot "dist\VideoDock-$releaseVersion-SHA256FILES.txt"))) {
        if (Test-Path -LiteralPath $target) { throw 'Release artifacts already exist. Use a new version and output folder.' }
    }
    $workerPath = [IO.Path]::GetFullPath((Join-Path $projectRoot 'vendor\VideoDockWorker.exe'))
    $runningCopies = Get-Process | Where-Object {
        try { $_.Path -and ($_.Path.StartsWith($releaseFolder + '\', [StringComparison]::OrdinalIgnoreCase) -or $_.Path -eq $workerPath) }
        catch { $false }
    }
    if ($runningCopies) { throw "Close the running copy of VideoDock $releaseVersion before rebuilding this release." }
    $inferencePython = Join-Path $projectRoot '.venv-inference\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $inferencePython)) { throw 'Run tools/setup_inference.py to prepare the local CUDA runtime.' }
    $runningInference = Get-Process | Where-Object {
        try { $_.Path -and $_.Path.StartsWith((Join-Path $projectRoot 'vendor\inference\'), [StringComparison]::OrdinalIgnoreCase) }
        catch { $false }
    }
    if ($runningInference) { throw 'An inference smoke is running. Finish it before building.' }
    & $Python tools/fetch_inference_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Verified inference dependencies are required.' }
    & $inferencePython -m PyInstaller --noconfirm --clean --distpath vendor --workpath build/inference-temp packaging/VideoDockInferenceWorker.spec
    if ($LASTEXITCODE -ne 0) { throw 'Inference runtime build failed.' }
    & $Python tools/fetch_dependencies.py
    if ($LASTEXITCODE -ne 0) { throw 'Verified dependencies are required for release builds.' }
    $catalogData = (Join-Path $projectRoot 'videodock\model_catalog.json') + ';videodock'
    & $Python -m PyInstaller --noconfirm --clean --onefile --console --name VideoDockWorker --distpath build/worker --workpath build/worker-temp --specpath build --exclude-module PySide6 --exclude-module yt_dlp --exclude-module torch --exclude-module transformers --exclude-module transcribe_cpp --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all tokenizers --collect-all av --collect-all sentencepiece --collect-all opencc --add-data $catalogData run_worker.py
    if ($LASTEXITCODE -ne 0) { throw 'Worker build failed.' }
    Copy-Item -LiteralPath 'build\worker\VideoDockWorker.exe' -Destination 'vendor\VideoDockWorker.exe'
    & $Python -m PyInstaller --noconfirm --clean packaging/VideoDock.spec
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
    if ($SkipInstaller) { return }
    if (-not $ISCC) {
        $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($compiler) { $ISCC = $compiler.Source }
        if (-not $ISCC) {
            $candidate = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
            if (Test-Path -LiteralPath $candidate) { $ISCC = $candidate }
        }
    }
    if (-not $ISCC) {
        & $Python tools/fetch_compiler.py
        if ($LASTEXITCODE -ne 0) { throw 'Portable compiler setup failed.' }
        $ISCC = Join-Path $projectRoot 'build\inno\ISCC.exe'
    }
    & $ISCC packaging/VideoDock.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
} finally {
    Pop-Location
}

