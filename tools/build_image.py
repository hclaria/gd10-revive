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
LAKKA_FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lakka")
# cpu_scaling_mode 4 is "Balanced": the default "Performance (Managed)" pins the CPU at max.
OVERRIDES = 'cpu_scaling_mode = "4"\n'
ROMS_OVERRIDES = ('system_directory = "/storage/roms/ROMS/bios"\n'
                  'rgui_browser_directory = "/storage/roms/ROMS"\n'
                  'playlist_directory = "/storage/roms/ROMS/playlists"\n')


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
# STORAGE is recreated on first boot, so our files ride on the FAT partition (/flash)
# and firstboot.sh installs them. Lakka loads units from /storage/.config/system.d.
FIRSTBOOT_HOOK = """
mkdir -p /storage/.config/system.d/multi-user.target.wants
cp /flash/gd10/gd10-thermal.service /storage/.config/system.d/
ln -sf ../gd10-thermal.service /storage/.config/system.d/multi-user.target.wants/gd10-thermal.service
if [ -d /flash/gd10/joypads ]; then
  mkdir -p /storage/joypads/udev
  cp /flash/gd10/joypads/*.cfg /storage/joypads/udev/
fi
"""


def install_gd10_files(img, p1_start, joypads_dir):
    target = f"{img}@@{p1_start * SECTOR}"
    env = dict(os.environ, MTOOLS_SKIP_CHECK="1")
    run("mmd", "-i", target, "::gd10", env=env)
    for name in ("gd10-thermal.sh", "gd10-thermal.service"):
        run("mcopy", "-i", target, os.path.join(LAKKA_FILES, name), f"::gd10/{name}", env=env)

    # Profiles for the pads sold with GD10 sticks ship with the repo, so a stick without
    # its stock card still gets the right buttons. Profiles from a stock card win on a clash.
    profiles = {os.path.basename(p): p for p in glob.glob(os.path.join(LAKKA_FILES, "joypads", "*.cfg"))}
    if joypads_dir:
        used = set()
        for path in sorted(glob.glob(os.path.join(joypads_dir, "*.cfg"))):
            if not os.path.getsize(path):
                continue
            # Vendor names differ only by trailing spaces, which RetroArch matches on.
            base = re.sub(r"[^A-Za-z0-9.-]+", "_", os.path.basename(path)[:-4]).strip("_")
            name, n = base, 2
            while name in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name)
            profiles[f"{name}.cfg"] = path

    run("mmd", "-i", target, "::gd10/joypads", env=env)
    with tempfile.TemporaryDirectory() as tmp:
        for name, path in sorted(profiles.items()):
            local = os.path.join(tmp, name)
            shutil.copyfile(path, local)
            run("mcopy", "-i", target, local, f"::gd10/joypads/{name}", env=env)

    fat_edit(img, p1_start, "firstboot.sh", lambda t: t.replace(FIRSTBOOT_MARK, FIRSTBOOT_MARK + FIRSTBOOT_HOOK, 1))
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

    print(f"installed thermal throttle, {install_gd10_files(a.output, p1_start, a.joypads)} gamepad profiles")
    overrides = OVERRIDES + (ROMS_OVERRIDES if a.card_bytes else "")
    fat_edit(a.output, p1_start, "retroarch-overrides.txt", lambda t: t.rstrip("\n") + "\n\n" + overrides)

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
        print(f"STORAGE {a.storage_mib} MiB, ROMS partition {(card_sectors - p3_start) * SECTOR / 1e9:.1f} GB (format it after flashing)")

    print(f"wrote {a.output} ({os.path.getsize(a.output) / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
