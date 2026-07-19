#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
    echo "error: $ROOT/.venv does not exist; install AGaMEMnon first" >&2
    exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export AGAMEMNON_OPENOCD="${AGAMEMNON_OPENOCD:-$HOME/.local/agamemnon-openocd/bin/openocd}"
export AGAMEMNON_OOCD_SCRIPTS="${AGAMEMNON_OOCD_SCRIPTS:-$HOME/.local/agamemnon-openocd/share/openocd/scripts}"
export AGAMEMNON_UARCH_NEXTPNR="${AGAMEMNON_UARCH_NEXTPNR:-$ROOT/third_party/nextpnr/build/nextpnr-generic}"

# --freq constrains timing; AGAMEMNON_SYSCLK selects the PLL emitted into the
# bitstream. Keep them equal so the hardware runs at the analyzed frequency.
export AGAMEMNON_SYSCLK=10

WORK="$ROOT/.tmp/video-demo"
BUILD="$ROOT/build/video-demo"
mkdir -p "$WORK" "$BUILD"

cat > "$WORK/blinky.v" <<'EOF'
module top(input wire clock, output wire led);
    reg [23:0] counter = 24'b0;
    always @(posedge clock)
        counter <= counter + 1'b1;
    assign led = counter[23];
endmodule
EOF

cat > "$WORK/blinky_L48.pcf" <<'EOF'
set_io led PIN_25
EOF

riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os \
    -nostdlib -ffreestanding -T examples/firmware/link.ld \
    -o "$WORK/clkcfg_stub.elf" examples/firmware/clkcfg_stub.c
riscv64-unknown-elf-objcopy -O binary \
    "$WORK/clkcfg_stub.elf" "$WORK/clkcfg_stub.bin"

pause() {
    printf '\n%s' "$1"
    read -r _
    printf '\n'
}

clear
printf 'AGaMEMnon: open FPGA build and hardware demo\n\n'

printf '$ agamemnon --version\n'
agamemnon --version

printf '\n$ agamemnon probe\n'
agamemnon probe

pause "Press Enter to show the Verilog..."

printf '$ sed -n "1,20p" .tmp/video-demo/blinky.v\n'
sed -n '1,20p' "$WORK/blinky.v"

pause "Press Enter to build..."

printf '%s\n' \
    '$ agamemnon build .tmp/video-demo/blinky.v --uarch --hard-carry \' \
    '    --pcf .tmp/video-demo/blinky_L48.pcf --freq 10 \' \
    '    --write-routed build/video-demo/blinky_routed.json \' \
    '    -o build/video-demo/blinky.bin'

agamemnon build "$WORK/blinky.v" --uarch \
    --hard-carry \
    --pcf "$WORK/blinky_L48.pcf" \
    --freq 10 \
    --write-routed "$BUILD/blinky_routed.json" \
    -o "$BUILD/blinky.bin"

printf '\nGenerated artifact:\n'
stat -c '  %n: %s bytes' "$BUILD/blinky.bin"

pause "Frame the board, then press Enter to program it..."

printf '%s\n' \
    '$ agamemnon sram .tmp/video-demo/clkcfg_stub.bin \' \
    '    --fabric build/video-demo/blinky.bin --words 1'

agamemnon sram "$WORK/clkcfg_stub.bin" \
    --fabric "$BUILD/blinky.bin" \
    --words 1

printf '\nThe onboard PIN_25 LED should now be blinking.\n'
printf 'The configuration is volatile; no flash was written.\n'
