#!/usr/bin/env python3
"""Inspect and patch the bootloader of Amlogic S905 (GXBB) SD cards.

The first MiB of a bootable SD card holds BL2 at sector 1, followed by a FIP
table at +0xC000 listing bl30, bl301, bl31 and bl33 (U-Boot). BL2 refuses to
start any stage whose SHA-256 does not match, so this tool checks every stage
and can swap bl33 for another U-Boot while keeping the original BL2/BL3x.
"""
import argparse
import hashlib
import struct
import sys

BOOT = 0x200
TOC = BOOT + 0xC000
LIMIT = 0x100000
HDR = struct.Struct("<4sIHHIIIIIIIIIIIII")
NAMES = {"9766fd3d": "bl30", "ddccbbaa": "bl301", "47d4086d": "bl31", "d6d0eea7": "bl33"}
BL33_UUID = bytes.fromhex("d6d0eea7")


def bl2_ok(img):
    o = BOOT + 0x10
    if img[o:o + 4] != b"@AML":
        return False
    off2 = struct.unpack_from("<I", img, o + 0x2C)[0]
    digest = hashlib.sha256(img[o:o + 0x40] + img[o + 0x60:o + 0x60 + off2]).digest()
    return digest == img[o + 0x40:o + 0x60]


def stage_digest(entry):
    # BL2 moves the last 0x60 bytes of each stage in front of the rest before hashing.
    size = len(entry)
    return hashlib.sha256(entry[:0x40] + entry[size - 0x60:] + entry[0x60:size - 0x60]).digest()


def toc_entries(img):
    if struct.unpack_from("<I", img, TOC)[0] != 0xAA640001:
        raise SystemExit("no FIP table at 0xC200: not an Amlogic GXBB bootloader")
    for i in range(4):
        e = TOC + 16 + i * 40
        off, size = struct.unpack_from("<QQ", img, e + 16)
        yield i, img[e:e + 4], TOC + off, size


def verify(img, quiet=False):
    ok = bl2_ok(img)
    report = [("BL2", ok, BOOT + 0x10, None)]
    gxb = b"plat/gxb" in img[BOOT:BOOT + 0xC000]
    for _, uuid, start, size in toc_entries(img):
        ent = img[start:start + size]
        good = ent[:4] == b"@AML" and struct.unpack_from("<I", ent, 4)[0] == size and stage_digest(ent) == ent[0x40:0x60]
        report.append((NAMES.get(uuid.hex(), uuid.hex()), good, start, start + size))
        ok &= good
    if not quiet:
        print(f"SoC family: {'GXBB (S905)' if gxb else 'unknown, not GXBB'}")
        for name, good, start, end in report:
            span = f"  {start:#08x}..{end:#08x}" if end else ""
            print(f"{name:6} {'OK' if good else 'BAD'}{span}")
    return report, gxb


def replace_bl33(img, uboot):
    uboot += bytes(-len(uboot) % 16)
    idx, _, start, _ = next(e for e in toc_entries(img) if e[1] == BL33_UUID)
    size = 0x60 + len(uboot)
    if start + size > LIMIT:
        raise SystemExit(f"U-Boot too large: would end at {start + size:#x}, limit {LIMIT:#x}")
    hdr = HDR.pack(b"@AML", size, 0x40, 1, 0x42424203, 0, 0x40, 0x20, 0x60, 0, 0x60, 0,
                   size - 0x60, 0, 0x60, size - 0x60, 0)
    entry = hdr + hashlib.sha256(hdr + uboot).digest() + uboot[0x60:] + uboot[:0x60]
    img[start:LIMIT] = bytes(LIMIT - start)
    img[start:start + size] = entry
    struct.pack_into("<Q", img, TOC + 16 + idx * 40 + 24, size)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check BL2 and every FIP stage")
    v.add_argument("dump", help="first MiB of the card (sudo dd ... bs=1m count=1)")
    r = sub.add_parser("replace-bl33", help="swap U-Boot, keep the original BL2/BL3x")
    r.add_argument("dump")
    r.add_argument("uboot", help="u-boot.bin built with TEXT_BASE 0x01000000")
    r.add_argument("output")
    a = p.parse_args()

    img = bytearray(open(a.dump, "rb").read(LIMIT))
    if len(img) < LIMIT:
        raise SystemExit(f"{a.dump} is shorter than 1 MiB")
    if a.cmd == "verify":
        report, gxb = verify(img)
        sys.exit(0 if gxb and all(r[1] for r in report) else 1)

    report, gxb = verify(img, quiet=True)
    if not gxb or not all(good for name, good, *_ in report if name != "bl33"):
        verify(img)
        raise SystemExit("refusing to patch: BL2 or a BL3x stage is damaged, or this is not a GXBB card")
    replace_bl33(img, open(a.uboot, "rb").read())
    report, _ = verify(img, quiet=True)
    assert all(r[1] for r in report)
    open(a.output, "wb").write(img)
    print(f"wrote {a.output}: all stages verified")


if __name__ == "__main__":
    main()
