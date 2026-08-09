param(
    [string]$Version = "0.1.1",
    [string]$Destination = "$HOME/.agamemnon/sdk-$Version"
)
$ErrorActionPreference = "Stop"
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') {
    throw "Invalid SDK version: $Version"
}
$Asset = "agamemnon-sdk-windows-x64.zip"
$Base = "https://github.com/bbenchoff/AGaMEMnon/releases/download/v$Version"
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) "agamemnon-$Version-$([guid]::NewGuid())"
$BundleRoot = Join-Path $Destination "agamemnon-sdk-windows-x64"

if (Test-Path -LiteralPath $Destination) {
    if (Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1) {
        throw "Install destination is not empty: $Destination"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $Temp,$Destination | Out-Null
    $Archive = Join-Path $Temp $Asset
    $Checksum = "$Archive.sha256"
    Invoke-WebRequest "$Base/$Asset" -OutFile $Archive
    Invoke-WebRequest "$Base/$Asset.sha256" -OutFile $Checksum
    $Expected = ((Get-Content -LiteralPath $Checksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
    if ($Expected -ne $Actual) { throw "Bundle SHA-256 mismatch" }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination

    $Wheel = @(Get-ChildItem -LiteralPath (Join-Path $BundleRoot "packages") `
        -Filter "agamemnon_ag32-*.whl")
    if ($Wheel.Count -ne 1) { throw "Expected one AGaMEMnon wheel, found $($Wheel.Count)" }
    python -m venv (Join-Path $BundleRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed" }
    $Python = Join-Path $BundleRoot ".venv/Scripts/python.exe"
    & $Python -m pip install --no-index `
        --find-links (Join-Path $BundleRoot "packages") $Wheel[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "Offline wheel installation failed" }

    . (Join-Path $BundleRoot "activate.ps1")
    & $Python -m agamemnon.cli doctor --no-hardware
    if ($LASTEXITCODE -ne 0) { throw "Installed SDK diagnostics failed" }
} finally {
    if (Test-Path -LiteralPath $Temp) {
        Remove-Item -LiteralPath $Temp -Recurse -Force
    }
}

Write-Host "Installed verified SDK at $BundleRoot"
Write-Host "For this shell: . '$BundleRoot/activate.ps1'"
