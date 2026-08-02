param(
    [string]$OutDir = ".tmp/riscv_mcu"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$OutPath = Join-Path $RepoRoot $OutDir

function Find-RiscvTool([string]$Name) {
    $Names = @($Name)
    if ($Name.StartsWith("riscv64-unknown-elf-")) {
        $Names += $Name.Replace("riscv64-unknown-elf-", "riscv-none-elf-")
    }
    foreach ($CandidateName in $Names) {
        $command = Get-Command $CandidateName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    $pioRoot = if ($env:PLATFORMIO_CORE_DIR) {
        $env:PLATFORMIO_CORE_DIR
    } else {
        Join-Path $env:USERPROFILE ".platformio"
    }
    foreach ($CandidateName in $Names) {
        $fallback = Join-Path $pioRoot "packages/toolchain-agrv/bin/$CandidateName.exe"
        if (Test-Path $fallback) {
            return $fallback
        }
    }
    throw "Cannot find $($Names -join ' or '). Put the RISC-V GNU toolchain on PATH or install the Agm32 PlatformIO package."
}

$Gcc = Find-RiscvTool "riscv64-unknown-elf-gcc"
$Objcopy = Find-RiscvTool "riscv64-unknown-elf-objcopy"
$GccMajor = [int]((& $Gcc -dumpversion).Split(".")[0])
$March = if ($GccMajor -ge 12) { "rv32imac_zicsr" } else { "rv32imac" }
New-Item -ItemType Directory -Force -Path $OutPath | Out-Null

$Common = @(
    "-march=$March", "-mabi=ilp32", "-Os", "-g",
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
        (Join-Path $RepoRoot "agamemnon/sdk/startup.S"),
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
Build-Example "uart_dma_loopback.c" "link_sram.ld" "uart_dma_loopback"
Build-Example "exception_mailbox.c" "link_sram.ld" "exception_mailbox"
Build-Example "software_interrupt.c" "link_sram.ld" "software_interrupt"
Build-Example "timer_interrupt.c" "link_sram.ld" "timer_interrupt"
Build-Example "local_interrupt0.c" "link_sram.ld" "local_interrupt0"
Build-Example "local_interrupt1.c" "link_sram.ld" "local_interrupt1"
Build-Example "local_interrupt2.c" "link_sram.ld" "local_interrupt2"
Build-Example "local_interrupt3.c" "link_sram.ld" "local_interrupt3"
Build-Example "crc_self_test.c" "link_sram.ld" "crc_self_test"
Build-Example "watchdog_snapshot.c" "link_sram.ld" "watchdog_snapshot"

Write-Host "Output: $OutPath"
