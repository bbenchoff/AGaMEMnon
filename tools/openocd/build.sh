#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 <linux|macos|windows> <prepared-source> <install-prefix>" >&2
    exit 2
fi

platform=$1
source_dir=$(cd "$2" && pwd)
mkdir -p "$3"
prefix=$(cd "$3" && pwd)
script_dir=$(cd "$(dirname "$0")" && pwd)
manifest="$script_dir/manifest.json"
if command -v python3 >/dev/null 2>&1; then
    python_cmd=python3
else
    python_cmd=python
fi

export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$("$python_cmd" -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_date_epoch"])' "$manifest")
export GIT_OPTIONAL_LOCKS=0
export TZ=UTC
export LC_ALL=C

if [[ "$platform" == windows ]]; then
    export ACLOCAL_PATH="${ACLOCAL_PATH:-/ucrt64/share/aclocal}"
fi

# Read arrays portably: macOS ships bash 3.2, which has no `mapfile`.
common_flags=()
while IFS= read -r line; do common_flags+=("$line"); done < <("$python_cmd" -c 'import json,sys; print(*json.load(open(sys.argv[1]))["configure"]["common"], sep="\n")' "$manifest")
platform_flags=()
while IFS= read -r line; do platform_flags+=("$line"); done < <("$python_cmd" -c 'import json,sys; print(*json.load(open(sys.argv[1]))["configure"][sys.argv[2]], sep="\n")' "$manifest" "$platform")
"$python_cmd" "$script_dir/release.py" verify-environment --platform "$platform"

cd "$source_dir"
./bootstrap

case "$platform" in
    windows)
        case "${MSYSTEM:-}" in
            UCRT64|MINGW64) ;;
            *) echo "Windows builds must run in an MSYS2 UCRT64 or MINGW64 shell" >&2; exit 2 ;;
        esac
        ;;
    linux|macos) ;;
    *) echo "unknown platform: $platform" >&2; exit 2 ;;
esac

./configure --prefix="$prefix" "${common_flags[@]}" "${platform_flags[@]}"
make -j"${AGAMEMNON_BUILD_JOBS:-2}"
make install

{
    echo "platform=$platform"
    echo "source_date_epoch=$SOURCE_DATE_EPOCH"
    echo "system=$(uname -a)"
    echo "compiler=$(${CC:-gcc} --version | head -1)"
    for dependency in libusb-1.0 hidapi hidapi-hidraw libjaylink capstone; do
        version=$(pkg-config --modversion "$dependency" 2>/dev/null || true)
        [[ -z "$version" ]] || echo "$dependency=$version"
    done
} > "$prefix/AGAMEMNON-BUILD-ENVIRONMENT.txt"

if [[ "$platform" == windows ]]; then
    tool_bin=$(dirname "$(command -v gcc)")
    cp "$tool_bin/libusb-1.0.dll" "$prefix/bin/"
    cp "$tool_bin/libhidapi-0.dll" "$prefix/bin/"
fi

if [[ "$platform" == windows ]]; then
    "$prefix/bin/openocd.exe" --version
else
    "$prefix/bin/openocd" --version
fi
