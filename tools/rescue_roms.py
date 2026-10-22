#!/usr/bin/env python3
"""Copy the readable games off a dying stock card, skipping corrupted archives.

    python3 tools/rescue_roms.py /Volumes/game/roms ~/gd10-roms

Stock GD10 cards are often worn out or fake-capacity: a good share of the files
are damaged and some reads hang. Every file is copied with a timeout, every
.zip is tested (and .7z when a 7z binary is installed), and bad ones are
dropped and listed in rescue.log. Run it again to resume: copied files are
skipped. Scraped media and save states, useless in Lakka, are left behind.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

SKIP_DIRS = {"downloaded_images", "media", "savestates", "bezels", "videos"}
SEVENZIP = shutil.which("7zz") or shutil.which("7z")


def archive_ok(path, name):
    low = name.lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                return z.testzip() is None
        except NotImplementedError:
            # Compression methods Python lacks (deflate64, implode): let 7z decide, else keep it.
            if not SEVENZIP:
                return True
        except (zipfile.BadZipFile, OSError, EOFError, ValueError):
            return False
    if low.endswith((".zip", ".7z")) and SEVENZIP:
        return subprocess.run([SEVENZIP, "t", path], capture_output=True).returncode == 0
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("src", help="roms folder of the stock card, e.g. /Volumes/game/roms")
    p.add_argument("dst", help="where to put the rescued files")
    p.add_argument("--skip", nargs="*", default=[], help="extra folders to leave out, e.g. psp")
    a = p.parse_args()

    skip = SKIP_DIRS | set(a.skip)
    os.makedirs(a.dst, exist_ok=True)
    log = open(os.path.join(a.dst, "rescue.log"), "a", buffering=1)
    stats = {"ok": 0, "bad": 0, "unreadable": 0}
    copied = 0
    t0 = time.time()

    def walk_error(err):
        log.write(f"LIST_ERROR\t{getattr(err, 'filename', '?')}\t{err}\n")

    for root, dirs, files in os.walk(a.src, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith("."))
        rel = os.path.relpath(root, a.src)
        for name in sorted(files):
            if name.startswith("."):
                continue
            src = os.path.join(root, name)
            dst = os.path.join(a.dst, rel, name)
            if os.path.exists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            part = dst + ".part"
            try:
                # cp in a subprocess so a read stuck on a bad sector can be killed.
                ok = subprocess.run(["cp", src, part], capture_output=True, timeout=300).returncode == 0
            except subprocess.TimeoutExpired:
                ok = False
            if not ok:
                stats["unreadable"] += 1
                log.write(f"UNREADABLE\t{src}\n")
            elif not archive_ok(part, name):
                stats["bad"] += 1
                log.write(f"BAD_ARCHIVE\t{src}\n")
            else:
                os.replace(part, dst)
                stats["ok"] += 1
                copied += os.path.getsize(dst)
            if os.path.exists(part):
                os.remove(part)
            n = sum(stats.values())
            if n % 500 == 0:
                print(f"{n} files, {stats}, {copied / 1e9:.1f} GB, now in {rel}", flush=True)

    total = sum(stats.values()) or 1
    print(f"done in {(time.time() - t0) / 60:.0f} min: {stats['ok']} saved ({100 * stats['ok'] // total}%), "
          f"{stats['bad']} corrupted archives, {stats['unreadable']} unreadable, {copied / 1e9:.1f} GB. "
          f"Details in {os.path.join(a.dst, 'rescue.log')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
