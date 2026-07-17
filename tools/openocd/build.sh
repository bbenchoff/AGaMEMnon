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

if [[ "$platform" == macos ]]; then
    # Make the release independent of the builder's Homebrew prefix. OpenOCD
    # should only acquire non-system dylibs from the two explicitly declared
    # runtime dependencies; fail closed if another Homebrew library appears.
    libusb_prefix=$(brew --prefix libusb)
    hidapi_prefix=$(brew --prefix hidapi)
    mkdir -p "$prefix/lib" "$prefix/share/licenses/libusb" "$prefix/share/licenses/hidapi"
    dylib_sources="$prefix/lib/.agamemnon-dylib-sources"
    : > "$dylib_sources"

    queue=("$prefix/bin/openocd")
    queue_index=0
    seen=$'\n'
    while (( queue_index < ${#queue[@]} )); do
        binary=${queue[$queue_index]}
        queue_index=$((queue_index + 1))
        case "$seen" in
            *$'\n'"$binary"$'\n'*) continue ;;
        esac
        seen+="$binary"$'\n'

        if [[ "$binary" != "$prefix/bin/openocd" ]]; then
            install_name_tool -id "@loader_path/$(basename "$binary")" "$binary"
        fi
        while IFS= read -r dependency; do
            case "$dependency" in
                "$libusb_prefix"/*|"$hidapi_prefix"/*)
                    ;;
                /opt/homebrew/*|/usr/local/Cellar/*|/usr/local/opt/*)
                    echo "unexpected Homebrew runtime dependency: $dependency" >&2
                    exit 1
                    ;;
                *)
                    continue
                    ;;
            esac
            name=$(basename "$dependency")
            bundled="$prefix/lib/$name"
            if [[ ! -f "$bundled" ]]; then
                cp -L "$dependency" "$bundled"
                chmod u+w "$bundled"
                printf '%s\t%s\n' "$name" "$dependency" >> "$dylib_sources"
                queue+=("$bundled")
            else
                original=$(awk -F '\t' -v name="$name" '$1 == name { print $2; exit }' "$dylib_sources")
                if [[ -z "$original" ]] || ! cmp -s "$dependency" "$original"; then
                    echo "conflicting macOS dylibs share the name $name" >&2
                    exit 1
                fi
            fi
            if [[ "$binary" == "$prefix/bin/openocd" ]]; then
                replacement="@loader_path/../lib/$name"
            else
                replacement="@loader_path/$name"
            fi
            install_name_tool -change "$dependency" "$replacement" "$binary"
        done < <(otool -L "$binary" | awk 'NR > 1 { print $1 }')
    done

    "$python_cmd" - "$manifest" "$prefix" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
prefix = Path(sys.argv[2])

def verified_download(item, destination):
    with urllib.request.urlopen(item["url"], timeout=60) as response:
        content = response.read()
    actual = hashlib.sha256(content).hexdigest()
    if actual != item["sha256"]:
        raise SystemExit(
            f"{destination.name} SHA-256 mismatch: {actual} "
            f"(expected {item['sha256']})"
        )
    destination.write_bytes(content)

for component, licenses in manifest["macos_runtime_licenses"].items():
    directory = prefix / "share" / "licenses" / component
    directory.mkdir(parents=True, exist_ok=True)
    for license_file in licenses:
        verified_download(license_file, directory / license_file["name"])

sources = prefix / "share" / "sources"
sources.mkdir(parents=True, exist_ok=True)
for source in manifest["macos_runtime_sources"].values():
    verified_download(source, sources / source["name"])
PY
    rm "$dylib_sources"

    if otool -L "$prefix/bin/openocd" "$prefix"/lib/*.dylib |
            grep -E '(/opt/homebrew|/usr/local/(Cellar|opt))'; then
        echo "macOS release still contains an external Homebrew load path" >&2
        exit 1
    fi
    runtime_libraries=$(DYLD_PRINT_LIBRARIES=1 "$prefix/bin/openocd" --version 2>&1)
    if grep -E '(/opt/homebrew|/usr/local/(Cellar|opt))' <<<"$runtime_libraries"; then
        echo "macOS release loaded a runtime library from Homebrew" >&2
        exit 1
    fi
fi

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
