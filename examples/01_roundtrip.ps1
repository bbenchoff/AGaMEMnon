# 01 - round-trip a fabric .bin through the open LZW codec, asserting byte-exact.
#
# decode: .bin -> 99936-byte raw fabric image
# encode: raw image -> .bin
# assert: re-encoded .bin == original .bin, byte for byte
#
# Offline: no hardware needed. Run from the repo root (so `agamemnon` is importable),
# or after `pip install -e .`.
$ErrorActionPreference = 'Stop'

# Input bitstream. Substitute your own .bin here.
if (-not $Bin) { $Bin = 'tests/fixtures/blinky.bin' }

# Scratch outputs.
$Tmp   = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ("agamemnon_" + [guid]::NewGuid()))
$Raw   = Join-Path $Tmp 'fabric.raw'
$Reenc = Join-Path $Tmp 'fabric.reenc.bin'

try {
    Write-Host "input: $Bin"

    python -m agamemnon.cli decode $Bin -o $Raw
    if ($LASTEXITCODE -ne 0) { throw "decode failed" }
    python -m agamemnon.cli encode $Raw -o $Reenc
    if ($LASTEXITCODE -ne 0) { throw "encode failed" }

    $a = [System.IO.File]::ReadAllBytes($Bin)
    $b = [System.IO.File]::ReadAllBytes($Reenc)
    $same = ($a.Length -eq $b.Length)
    if ($same) {
        for ($i = 0; $i -lt $a.Length; $i++) {
            if ($a[$i] -ne $b[$i]) { $same = $false; break }
        }
    }

    if ($same) {
        Write-Host "ROUND-TRIP BYTE-EXACT OK"
    } else {
        Write-Host "ROUND-TRIP MISMATCH"
        Write-Host "  (If your .bin has trailing flash padding past the LZW stream, the re-encoded"
        Write-Host "   file may be shorter. The supplied blinky.bin matches exactly.)"
        exit 1
    }
}
finally {
    Remove-Item -Recurse -Force $Tmp
}
