#!/bin/sh
# Builds mainline U-Boot for the GD10 (p200 + gd10.config) inside Docker.
# Output: build/u-boot.bin
set -eu
cd "$(dirname "$0")/.."
UBOOT_TAG=v2024.01
IMAGE=gd10-revive-builder

docker build -q -t "$IMAGE" uboot >/dev/null
mkdir -p build
[ -d build/u-boot ] || git clone -q --depth 1 -b "$UBOOT_TAG" https://github.com/u-boot/u-boot build/u-boot

docker run --rm -v "$PWD:/w" -w /w/build/u-boot "$IMAGE" sh -c '
  export CROSS_COMPILE=aarch64-linux-gnu-
  cat configs/p200_defconfig /w/uboot/gd10.config > configs/gd10_defconfig
  make gd10_defconfig >/dev/null
  make -j"$(nproc)" >/w/build/u-boot-build.log 2>&1 || { tail -20 /w/build/u-boot-build.log; exit 1; }
  cp u-boot.bin /w/build/u-boot.bin
'
echo "build/u-boot.bin ($(wc -c < build/u-boot.bin) bytes)"
