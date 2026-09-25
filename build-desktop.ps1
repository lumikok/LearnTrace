$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
}

& $python -m pip install -r requirements-desktop.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed --name '拾光' --add-data 'static;static' --collect-submodules webview.platforms --hidden-import clr desktop.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
$appDirectory = Join-Path $PSScriptRoot 'dist\拾光'
$archive = Join-Path $PSScriptRoot "dist\拾光-$version-win64.zip"
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'DISTRIBUTION.txt') -Destination (Join-Path $appDirectory '使用说明.txt') -Force
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Compress-Archive -LiteralPath $appDirectory -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Value $hash -Encoding ascii
Write-Host "构建完成：$archive"
Write-Host "SHA256：$hash"
