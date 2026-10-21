#!/bin/sh
# Builds a bootable SD card image for the GD10 S905 game stick.
#
# usage: ./make-image.sh (--dump stock-card-1MiB.bin | --bootloader bootloader.bin)
#                        [--card-bytes N] [--joypads-from stock-storage.img | DIR]
set -eu
cd "$(dirname "$0")"

LAKKA_VERSION=6.1
LAKKA_FILE="Lakka-AMLGX.aarch64-${LAKKA_VERSION}-box.img.gz"
LAKKA_URL="https://github.com/libretro/Lakka-LibreELEC/releases/download/v${LAKKA_VERSION}/${LAKKA_FILE}"
IMAGE=gd10-revive-builder

DUMP= BOOTLOADER= CARD_BYTES= JOYPADS=
while [ $# -gt 0 ]; do
  case "$1" in
    --dump) DUMP=$2; shift 2 ;;
    --bootloader) BOOTLOADER=$2; shift 2 ;;
    --card-bytes) CARD_BYTES=$2; shift 2 ;;
    --joypads-from) JOYPADS=$2; shift 2 ;;
    *) sed -n '2,6p' "$0"; exit 1 ;;
  esac
done
[ -n "$DUMP$BOOTLOADER" ] || { sed -n '2,6p' "$0"; exit 1; }

mkdir -p build
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

if [ -n "$DUMP" ]; then
  [ -f build/u-boot.bin ] || ./uboot/build.sh
  python3 tools/aml_fip.py replace-bl33 "$DUMP" build/u-boot.bin build/bootloader.bin
  BOOTLOADER=build/bootloader.bin
else
  python3 tools/aml_fip.py verify "$BOOTLOADER"
fi

if [ ! -f "build/${LAKKA_FILE%.gz}" ]; then
  (cd build && curl -fSL --retry 5 -C - -O "$LAKKA_URL" -O "$LAKKA_URL.sha256" && sha256 -c "$LAKKA_FILE.sha256")
  gunzip -k "build/$LAKKA_FILE"
fi

cp "$BOOTLOADER" build/bootloader-in.bin
docker build -q -t "$IMAGE" uboot >/dev/null

if [ -f "$JOYPADS" ]; then
  # Stock EmuELEC STORAGE partition: its /joypads holds the vendor's RetroArch profiles.
  rm -rf build/joypads && mkdir -p build/joypads
  cp "$JOYPADS" build/stock-storage.img
  docker run --rm -v "$PWD:/w" -w /w/build/joypads "$IMAGE" \
    debugfs -R "rdump /joypads /w/build/joypads" /w/build/stock-storage.img 2>/dev/null
  rm build/stock-storage.img
  JOYPADS=build/joypads/joypads
elif [ -d "$JOYPADS" ]; then
  rm -rf build/joypads && mkdir -p build/joypads && cp "$JOYPADS"/*.cfg build/joypads/
  JOYPADS=build/joypads
fi

docker run --rm -v "$PWD:/w" -w /w "$IMAGE" python3 tools/build_image.py \
  "build/${LAKKA_FILE%.gz}" build/bootloader-in.bin build/gd10-lakka.img \
  ${CARD_BYTES:+--card-bytes "$CARD_BYTES"} ${JOYPADS:+--joypads "$JOYPADS"}

cat <<EOF

Flash build/gd10-lakka.img to the card (check the disk number first!):
  macOS:  diskutil unmountDisk /dev/diskN && sudo dd if=build/gd10-lakka.img of=/dev/rdiskN bs=4m status=progress
  Linux:  sudo dd if=build/gd10-lakka.img of=/dev/sdX bs=4M status=progress conv=fsync
EOF
[ -z "$CARD_BYTES" ] || cat <<EOF
Then format the ROMS partition (3rd partition):
  macOS:  diskutil eraseVolume ExFAT ROMS /dev/diskNs3
  Linux:  sudo mkfs.exfat -n ROMS /dev/sdX3
EOF
