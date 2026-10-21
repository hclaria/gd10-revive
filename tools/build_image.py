#!/usr/bin/env python3
"""Turn the Lakka AMLGX "box" image into a bootable GD10 (S905) SD card image.

Runs inside the builder container (needs e2fsprogs and mtools).
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
ROMS_OVERRIDES = 'system_directory = "/var/media/ROMS/bios"\nrgui_browser_directory = "/var/media/ROMS"\n'


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


def add_joypads(storage, src_dir):
    # Lakka overlays /storage/joypads on its own autoconfig profiles at /tmp/joypads.
    profiles = [p for p in sorted(glob.glob(os.path.join(src_dir, "*.cfg"))) if os.path.getsize(p)]
    cmds = ["mkdir /joypads", "mkdir /joypads/udev"]
    used = set()
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(profiles):
            local = os.path.join(tmp, f"{i}.cfg")
            shutil.copyfile(path, local)
            # Vendor names differ only by trailing spaces, which RetroArch matches on.
            base = re.sub(r"[^A-Za-z0-9.-]+", "_", os.path.basename(path)[:-4]).strip("_")
            name, n = base, 2
            while name in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name)
            cmds.append(f"write {local} /joypads/udev/{name}.cfg")
        script = os.path.join(tmp, "cmds")
        open(script, "w").write("\n".join(cmds) + "\n")
        run("debugfs", "-w", "-f", script, storage)
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

    new_p2 = a.storage_mib * MiB // SECTOR if a.card_bytes else p2_size
    if a.card_bytes or a.joypads:
        with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(a.output))) as tmp:
            p2 = os.path.join(tmp, "p2.img")
            with open(a.output, "rb") as src, open(p2, "wb") as dst:
                src.seek(p2_start * SECTOR)
                dst.write(src.read(p2_size * SECTOR))
            if a.card_bytes:
                os.truncate(p2, new_p2 * SECTOR)
                subprocess.run(["e2fsck", "-fy", p2], capture_output=True)
                run("resize2fs", p2)
                # Without this marker Lakka keeps STORAGE at this size instead of growing it over ROMS.
                run("debugfs", "-w", "-R", "rm /.please_resize_me", p2)
            if a.joypads:
                print(f"preinstalled {add_joypads(p2, a.joypads)} gamepad profiles")
            with open(a.output, "r+b") as dst, open(p2, "rb") as src:
                dst.seek(p2_start * SECTOR)
                shutil.copyfileobj(src, dst, 16 * MiB)
                if a.card_bytes:
                    dst.truncate((p2_start + new_p2) * SECTOR)

    if a.card_bytes:
        card_sectors = a.card_bytes // SECTOR
        p3_start = p2_start + new_p2
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
