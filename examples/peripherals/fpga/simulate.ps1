param([string]$OutDir = ".tmp/peripherals")
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$Out = Join-Path $RepoRoot $OutDir
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if ($env:AGAMEMNON_OSS) {
    $env:PATH = (Join-Path $env:AGAMEMNON_OSS "bin") + ";" +
                (Join-Path $env:AGAMEMNON_OSS "lib") + ";" + $env:PATH
}

function Find-OssTool([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if ($env:AGAMEMNON_OSS) {
        $candidate = Join-Path $env:AGAMEMNON_OSS "bin/$Name.exe"
        if (Test-Path $candidate) { return $candidate }
        $candidate = Join-Path $env:AGAMEMNON_OSS "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    throw "Cannot find $Name; put Icarus Verilog on PATH or set AGAMEMNON_OSS."
}

$Iverilog = Find-OssTool "iverilog"
$Vvp = Find-OssTool "vvp"
$Sources = @(
    "timer_tick.v", "gpio_walker.v", "pwm4.v", "uart_tx.v",
    "spi_master.v", "i2c_writer.v", "peripheral_showcase.v",
    "tb_peripheral_showcase.v"
) | ForEach-Object { Join-Path $PSScriptRoot $_ }
$Image = Join-Path $Out "peripheral_showcase_tb.vvp"

& $Iverilog -g2012 -s tb_peripheral_showcase -o $Image @Sources
if ($LASTEXITCODE -ne 0) { throw "iverilog failed" }
& $Vvp $Image
if ($LASTEXITCODE -ne 0) { throw "simulation failed" }
