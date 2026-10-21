#!/usr/bin/env python3
"""Turn the Lakka AMLGX "box" image into a bootable GD10 (S905) SD card image.

Runs inside the builder container (needs mtools).
"""
import argparse
import glob
import os
import re
import shutil
import struct
import subprocess
import tempfile

SECTOR = 512
MiB = 1024 * 1024
DTB = "/amlogic/meson-gxbb-p200.dtb"
ROMS_OVERRIDES = 'system_directory = "/storage/roms/ROMS/bios"\nrgui_browser_directory = "/storage/roms/ROMS"\n'


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def partitions(path):
    with open(path, "rb") as f:
        mbr = f.read(SECTOR)
    assert mbr[510:512] == b"\x55\xaa", "no MBR"
    return [struct.unpack_from("<II", mbr, 446 + 16 * i + 8) for i in range(4)], mbr


def fat_edit(img, p1_start, name, edit):
    target = f"{img}@@{p1_start * SECTOR}"
    env = dict(os.environ, MTOOLS_SKIP_CHECK="1")
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, name)
        run("mcopy", "-n", "-i", target, f"::{name}", local, env=env)
        text = open(local).read()
        open(local, "w").write(edit(text))
        run("mcopy", "-o", "-i", target, local, f"::{name}", env=env)


FIRSTBOOT_MARK = "# v v v v v v v v v v v v v v v v v v v v\n"
JOYPADS_HOOK = """
if [ -d /flash/gd10/joypads ]; then
  mkdir -p /storage/joypads/udev
  cp /flash/gd10/joypads/*.cfg /storage/joypads/udev/
fi
"""


def add_joypads(img, p1_start, src_dir):
    # STORAGE is recreated on first boot, so the profiles ride on the FAT partition and
    # firstboot.sh copies them into /storage/joypads, which Lakka overlays on its own set.
    profiles = [p for p in sorted(glob.glob(os.path.join(src_dir, "*.cfg"))) if os.path.getsize(p)]
    target = f"{img}@@{p1_start * SECTOR}"
    env = dict(os.environ, MTOOLS_SKIP_CHECK="1")
    run("mmd", "-i", target, "::gd10", "::gd10/joypads", env=env)
    used = set()
    with tempfile.TemporaryDirectory() as tmp:
        for path in profiles:
            # Vendor names differ only by trailing spaces, which RetroArch matches on.
            base = re.sub(r"[^A-Za-z0-9.-]+", "_", os.path.basename(path)[:-4]).strip("_")
            name, n = base, 2
            while name in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name)
            local = os.path.join(tmp, f"{name}.cfg")
            shutil.copyfile(path, local)
            run("mcopy", "-i", target, local, f"::gd10/joypads/{name}.cfg", env=env)
    fat_edit(img, p1_start, "firstboot.sh", lambda t: t.replace(FIRSTBOOT_MARK, FIRSTBOOT_MARK + JOYPADS_HOOK, 1))
    return len(profiles)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("lakka_img")
    p.add_argument("bootloader", help="1 MiB bootloader from aml_fip.py replace-bl33")
    p.add_argument("output")
    p.add_argument("--card-bytes", type=int, help="card size; adds a ROMS partition after a fixed STORAGE")
    p.add_argument("--storage-mib", type=int, default=4096)
    p.add_argument("--joypads", help="directory of RetroArch gamepad profiles (*.cfg) to preinstall")
    a = p.parse_args()

    boot = open(a.bootloader, "rb").read()
    assert len(boot) == MiB
    parts, _ = partitions(a.lakka_img)
    (p1_start, _), (p2_start, p2_size) = parts[0], parts[1]
    assert p1_start * SECTOR >= MiB, "first partition overlaps the bootloader area"

    shutil.copyfile(a.lakka_img, a.output)
    with open(a.output, "r+b") as f:
        # Bytes 444-511 of sector 0 keep the Lakka partition table.
        f.seek(0)
        f.write(boot[:444])
        f.seek(SECTOR)
        f.write(boot[SECTOR:])

    fat_edit(a.output, p1_start, "uEnv.ini", lambda t: "\n".join(
        f"dtb_name={DTB}" if line.startswith("dtb_name=") else line.replace(" quiet ", " ")
        for line in t.splitlines()) + "\n")

    if a.joypads:
        print(f"bundled {add_joypads(a.output, p1_start, a.joypads)} gamepad profiles")

    if a.card_bytes:
        # Lakka's first boot runs "parted resizepart 2 100%", which fails harmlessly with a
        # partition after STORAGE, then recreates the file system over the whole 2nd partition.
        card_sectors = a.card_bytes // SECTOR
        new_p2 = a.storage_mib * MiB // SECTOR
        p3_start = p2_start + new_p2
        assert new_p2 >= p2_size, "STORAGE would shrink"
        assert card_sectors > p3_start + 1024 * MiB // SECTOR, "card too small for a ROMS partition"
        with open(a.output, "r+b") as f:
            mbr = bytearray(f.read(SECTOR))
            struct.pack_into("<I", mbr, 446 + 16 + 12, new_p2)
            p3 = bytearray(16)
            p3[4] = 0x07
            struct.pack_into("<II", p3, 8, p3_start, card_sectors - p3_start)
            mbr[446 + 32:446 + 48] = p3
            f.seek(0)
            f.write(mbr)
        fat_edit(a.output, p1_start, "retroarch-overrides.txt", lambda t: t.rstrip("\n") + "\n\n" + ROMS_OVERRIDES)
        print(f"STORAGE {a.storage_mib} MiB, ROMS partition {(card_sectors - p3_start) * SECTOR / 1e9:.1f} GB (format it after flashing)")

    print(f"wrote {a.output} ({os.path.getsize(a.output) / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
