param(
    [string]$Version = "0.1.0",
    [string]$Destination = "$HOME/.agamemnon/sdk-$Version"
)
$ErrorActionPreference = "Stop"
$Asset = "agamemnon-sdk-windows-x64.zip"
$Base = "https://github.com/bbenchoff/AGaMEMnon/releases/download/v$Version"
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) "agamemnon-$Version"
New-Item -ItemType Directory -Force -Path $Temp | Out-Null
$Archive = Join-Path $Temp $Asset
$Checksum = "$Archive.sha256"
Invoke-WebRequest "$Base/$Asset" -OutFile $Archive
Invoke-WebRequest "$Base/$Asset.sha256" -OutFile $Checksum
$Expected = ((Get-Content -LiteralPath $Checksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
if ($Expected -ne $Actual) { throw "bundle SHA-256 mismatch" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
Write-Host "Installed verified bundle at $Destination"
Write-Host "Run: . '$Destination/agamemnon-sdk-windows-x64/activate.ps1'"
Write-Host "Then install its wheel and run: agamemnon doctor"
