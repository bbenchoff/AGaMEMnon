#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
	echo "usage: $0 <verified-prepared-root> <fresh-build-root>" >&2
	exit 2
fi

prepared_root=$(cd "$1" && pwd)
mkdir -p "$2"
build_root=$(cd "$2" && pwd)
if find "$build_root" -mindepth 1 -print -quit | grep -q .; then
	echo "Phase1C build root must be empty: $build_root" >&2
	exit 2
fi

case "${MSYSTEM:-}" in
	UCRT64) ;;
	*) echo "Phase1C requires the frozen MSYS2 UCRT64 environment" >&2; exit 2 ;;
esac

export SOURCE_DATE_EPOCH=1777198205
export TZ=UTC
export LC_ALL=C
export CONFIG_SITE=/dev/null
export ACLOCAL_PATH=/ucrt64/share/aclocal

script_dir=$(cd "$(dirname "$0")" && pwd)
python_script=$(cygpath -w "$script_dir/phase1c.py")
prepared_windows=$(cygpath -w "$prepared_root")
/c/Python312/python.exe "$python_script" verify-prepared --prepared-root "$prepared_windows"

cp -a "$prepared_root/openocd-source" "$build_root/openocd-source"
cp -a "$prepared_root/libusb-source" "$build_root/libusb-source"
openocd_source="$build_root/openocd-source"
libusb_source="$build_root/libusb-source"

common_cflags=(
	-O2
	-g0
	"-ffile-prefix-map=$build_root=/usr/src/r6-phase1c"
	"-fdebug-prefix-map=$build_root=/usr/src/r6-phase1c"
)

libusb_build="$build_root/libusb-build"
libusb_stage="$build_root/libusb-stage"
libusb_install_prefix=/opt/agamemnon-libusb
libusb_prefix="$libusb_stage$libusb_install_prefix"
mkdir -p "$libusb_build" "$libusb_stage"
(
	cd "$libusb_source"
	autoreconf -fiv
)
(
	cd "$libusb_build"
	CFLAGS="${common_cflags[*]}" \
	LDFLAGS="-static -static-libgcc -Wl,--no-insert-timestamp" \
	ARFLAGS=crD \
	"$libusb_source/configure" \
		--build=x86_64-w64-mingw32 \
		--host=x86_64-w64-mingw32 \
		--prefix="$libusb_install_prefix" \
		--disable-shared \
		--enable-static \
		--disable-examples-build \
		--disable-tests-build \
		--disable-udev \
		--disable-system-log
	make -j"${AGAMEMNON_BUILD_JOBS:-2}" V=1 2>&1 | tee "$build_root/libusb-build.log"
	make install DESTDIR="$libusb_stage" 2>&1 | tee "$build_root/libusb-install.log"
)

openocd_build="$build_root/openocd-build"
openocd_stage="$build_root/openocd-stage"
openocd_install_prefix=/opt/agamemnon-openocd
mkdir -p "$openocd_build" "$openocd_stage"
(
	cd "$openocd_source"
	./bootstrap nosubmodule
)

adapter_flags=(
	--enable-cmsis-dap-v2
	--disable-am335xgpio
	--disable-amtjtagaccel
	--disable-angie
	--disable-armjtagew
	--disable-at91rm9200
	--disable-bcm2835gpio
	--disable-buspirate
	--disable-ch347
	--disable-cmsis-dap
	--disable-cmsis-dap-tcp
	--disable-dmem
	--disable-dummy
	--disable-ep93xx
	--disable-esp-usb-jtag
	--disable-ft232r
	--disable-ftdi
	--disable-ftdi-cjtag
	--disable-imx-gpio
	--disable-jlink
	--disable-jtag-dpi
	--disable-jtag-vpi
	--disable-kitprog
	--disable-linuxgpiod
	--disable-linuxspidev
	--disable-nulink
	--disable-opendous
	--disable-openjtag
	--disable-osbdm
	--disable-parport
	--disable-presto
	--disable-remote-bitbang
	--disable-rlink
	--disable-rshim
	--disable-stlink
	--disable-sysfsgpio
	--disable-ti-icdi
	--disable-ulink
	--disable-usb-blaster
	--disable-usb-blaster-2
	--disable-usbprog
	--disable-vdebug
	--disable-vsllink
	--disable-xds110
	--disable-xlnx-xvc
)

(
	cd "$openocd_build"
	export PKG_CONFIG_PATH=
	export PKG_CONFIG_LIBDIR="$libusb_prefix/lib/pkgconfig"
	export CPPFLAGS="-I$libusb_prefix/include/libusb-1.0"
	export CFLAGS="${common_cflags[*]}"
	export LDFLAGS="-L$libusb_prefix/lib -static -static-libgcc -Wl,--no-insert-timestamp"
	export LIBUSB1_CFLAGS="-I$libusb_prefix/include/libusb-1.0"
	export LIBUSB1_LIBS="-L$libusb_prefix/lib -lusb-1.0 -lwinusb -lcfgmgr32 -ladvapi32 -lsetupapi -lhid -lole32 -luser32"
	"$openocd_source/configure" \
		--prefix="$openocd_install_prefix" \
		--build=x86_64-w64-mingw32 \
		--host=x86_64-w64-mingw32 \
		--enable-internal-jimtcl \
		--disable-internal-libjaylink \
		--disable-capstone \
		--disable-doxygen-html \
		--disable-doxygen-pdf \
		--disable-werror \
		"${adapter_flags[@]}"
	make -j"${AGAMEMNON_BUILD_JOBS:-2}" V=1 2>&1 | tee "$build_root/openocd-build.log"
	make install DESTDIR="$openocd_stage" 2>&1 | tee "$build_root/openocd-install.log"
)

echo "PASS_PHASE1C_BUILD_COMPLETE_OPENOCD_NOT_EXECUTED"
