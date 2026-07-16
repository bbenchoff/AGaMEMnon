param(
    [string]$OutDir = ".tmp/riscv_mcu"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$OutPath = Join-Path $RepoRoot $OutDir

function Find-RiscvTool([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $pioRoot = if ($env:PLATFORMIO_CORE_DIR) {
        $env:PLATFORMIO_CORE_DIR
    } else {
        Join-Path $env:USERPROFILE ".platformio"
    }
    $fallback = Join-Path $pioRoot "packages/toolchain-agrv/bin/$Name.exe"
    if (Test-Path $fallback) {
        return $fallback
    }
    throw "Cannot find $Name. Put the RISC-V GNU toolchain on PATH or install the Agm32 PlatformIO package."
}

$Gcc = Find-RiscvTool "riscv64-unknown-elf-gcc"
$Objcopy = Find-RiscvTool "riscv64-unknown-elf-objcopy"
New-Item -ItemType Directory -Force -Path $OutPath | Out-Null

$Common = @(
    "-march=rv32imac", "-mabi=ilp32", "-Os", "-g",
    "-nostdlib", "-ffreestanding", "-fno-builtin",
    "-ffunction-sections", "-fdata-sections",
    "-I", (Join-Path $RepoRoot "mcu")
)

function Build-Example([string]$Source, [string]$Linker, [string]$Name) {
    $Elf = Join-Path $OutPath "$Name.elf"
    $Bin = Join-Path $OutPath "$Name.bin"
    $Map = Join-Path $OutPath "$Name.map"
    $Args = $Common + @(
        "-T", (Join-Path $PSScriptRoot $Linker),
        "-Wl,--gc-sections", "-Wl,-Map,$Map",
        (Join-Path $PSScriptRoot "startup.S"),
        (Join-Path $PSScriptRoot $Source),
        "-o", $Elf
    )
    & $Gcc @Args
    if ($LASTEXITCODE -ne 0) { throw "GCC failed for $Name" }
    & $Objcopy -O binary $Elf $Bin
    if ($LASTEXITCODE -ne 0) { throw "objcopy failed for $Name" }
    Write-Host ("{0,-26} {1,6} bytes" -f $Name, (Get-Item $Bin).Length)
}

Build-Example "sram_signature.c" "link_sram.ld" "sram_signature"
Build-Example "reset_counter.c" "link_flash.ld" "reset_counter_flash"
Build-Example "led_blink.c" "link_flash.ld" "led_blink_flash"
Build-Example "led_blink.c" "link_usb_app.ld" "led_blink_usb_app"
Build-Example "timer_led_walk.c" "link_flash.ld" "timer_led_walk_flash"
Build-Example "timer_led_walk.c" "link_usb_app.ld" "timer_led_walk_usb_app"
Build-Example "hard_peripheral_inventory.c" "link_sram.ld" "hard_peripheral_inventory"
Build-Example "basic_timer_led_walk.c" "link_flash.ld" "basic_timer_led_walk_flash"
Build-Example "basic_timer_led_walk.c" "link_usb_app.ld" "basic_timer_led_walk_usb_app"

Write-Host "Output: $OutPath"
