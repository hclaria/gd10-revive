#!/usr/bin/env python3
"""Write RetroArch playlists for a ROMS folder laid out like the stock EmuELEC card.

Scanning 20 000+ files on the S905 takes hours, so build the playlists on your
computer instead:

    python3 tools/make_playlists.py /Volumes/ROMS

They go to ROMS/playlists, where the image points RetroArch, with the right
system name (for icons and thumbnails) and a default core per system.
"""
import argparse
import html
import json
import os
import re

CORES = "/tmp/cores"

# folder: (playlist / database name, core, extensions, take labels from gamelist.xml)
SYSTEMS = {
    "amiga1200": ("Commodore - Amiga", "puae", "lha lzx adf zip", False),
    "amstradcpc": ("Amstrad - CPC", "cap32", "dsk cdt", False),
    "arcade": ("MAME 2003-Plus", "mame2003_plus", "zip", True),
    "atari5200": ("Atari - 5200", "a5200", "zip a52", False),
    "atari7800": ("Atari - 7800", "prosystem", "zip a78", False),
    "atari800": ("Atari - 8-bit", "atari800", "zip atr xex", False),
    "atarilynx": ("Atari - Lynx", "handy", "zip lnx", False),
    "atarist": ("Atari - ST", "hatari", "st msa stx zip", False),
    "c64": ("Commodore - 64", "vice_x64", "d64 t64 crt d81 prg", False),
    "dreamcast": ("Sega - Dreamcast", "flycast", "cdi chd gdi", False),
    "fbneo": ("FBNeo - Arcade Games", "fbneo", "zip", True),
    "fds": ("Nintendo - Family Computer Disk System", "fceumm", "zip fds", False),
    "gameandwatch": ("Handheld Electronic Game", "gw", "zip mgw", False),
    "gamegear": ("Sega - Game Gear", "genesis_plus_gx", "zip gg", False),
    "gb": ("Nintendo - Game Boy", "gambatte", "zip gb", False),
    "gba": ("Nintendo - Game Boy Advance", "mgba", "zip gba", False),
    "gbc": ("Nintendo - Game Boy Color", "gambatte", "zip gbc", False),
    "genesis": ("Sega - Mega Drive - Genesis", "genesis_plus_gx", "zip md gen smd bin", False),
    "megadrive": ("Sega - Mega Drive - Genesis", "genesis_plus_gx", "zip md gen smd bin", False),
    "mastersystem": ("Sega - Master System - Mark III", "genesis_plus_gx", "zip sms", False),
    "msx": ("Microsoft - MSX", "bluemsx", "zip rom mx1 dsk", False),
    "msx2": ("Microsoft - MSX2", "bluemsx", "zip rom mx2 dsk", False),
    "n64": ("Nintendo - Nintendo 64", "mupen64plus_next", "n64 z64 v64 zip", False),
    "naomi": ("Sega - Naomi", "flycast", "zip", True),
    "nds": ("Nintendo - Nintendo DS", "melonds", "zip nds", False),
    "neogeo": ("SNK - Neo Geo", "fbneo", "zip", True),
    "nes": ("Nintendo - Nintendo Entertainment System", "fceumm", "zip nes", False),
    "nesh": ("Nintendo - Nintendo Entertainment System", "fceumm", "zip nes", False),
    "ngp": ("SNK - Neo Geo Pocket", "mednafen_ngp", "zip ngp", False),
    "ngpc": ("SNK - Neo Geo Pocket Color", "mednafen_ngp", "zip ngc", False),
    "odyssey": ("Magnavox - Odyssey2", "o2em", "zip bin", False),
    "pcenginecd": ("NEC - PC Engine CD - TurboGrafx-CD", "mednafen_pce_fast", "chd cue", False),
    "pokemini": ("Nintendo - Pokemon Mini", "pokemini", "zip min", False),
    "psx": ("Sony - PlayStation", "pcsx_rearmed", "chd pbp cue m3u iso img", False),
    "sega32x": ("Sega - 32X", "picodrive", "zip 32x", False),
    "segacd": ("Sega - Mega-CD - Sega CD", "genesis_plus_gx", "chd cue", False),
    "sg-1000": ("Sega - SG-1000", "genesis_plus_gx", "zip sg", False),
    "sgfx": ("NEC - PC Engine SuperGrafx", "mednafen_supergrafx", "zip sgx pce", False),
    "snes": ("Nintendo - Super Nintendo Entertainment System", "snes9x2010", "zip sfc smc", False),
    "vectrex": ("GCE - Vectrex", "vecx", "zip vec", False),
    "virtualboy": ("Nintendo - Virtual Boy", "mednafen_vb", "zip vb", False),
    "zxspectrum": ("Sinclair - ZX Spectrum", "fuse", "tzx tap z80 pzx", False),
}

CORE_NAMES = {
    "a5200": "Atari - 5200 (a5200)",
    "atari800": "Atari - 400/800/600XL/800XL/130XE/5200 (Atari800)",
    "bluemsx": "MSX/SVI/ColecoVision/SG-1000 (blueMSX)",
    "cap32": "Amstrad - CPC/GX4000 (Caprice32)",
    "fbneo": "Arcade (FinalBurn Neo)",
    "fceumm": "Nintendo - NES / Famicom (FCEUmm)",
    "flycast": "Sega - Dreamcast/Naomi (Flycast)",
    "fuse": "Sinclair - ZX Spectrum (Fuse)",
    "gambatte": "Nintendo - Game Boy / Color (Gambatte)",
    "genesis_plus_gx": "Sega - MS/GG/MD/CD (Genesis Plus GX)",
    "gw": "Handheld Electronic (GW)",
    "handy": "Atari - Lynx (Handy)",
    "hatari": "Atari - ST/STE/TT/Falcon (Hatari)",
    "mame2003_plus": "Arcade (MAME 2003-Plus)",
    "mednafen_ngp": "SNK - Neo Geo Pocket / Color (Beetle NeoPop)",
    "mednafen_pce_fast": "NEC - PC Engine / CD (Beetle PCE FAST)",
    "mednafen_supergrafx": "NEC - PC Engine SuperGrafx (Beetle SuperGrafx)",
    "mednafen_vb": "Nintendo - Virtual Boy (Beetle VB)",
    "melonds": "Nintendo - DS (melonDS)",
    "mgba": "Nintendo - Game Boy Advance (mGBA)",
    "mupen64plus_next": "Nintendo - Nintendo 64 (Mupen64Plus-Next)",
    "o2em": "Magnavox - Odyssey2 / Philips Videopac+ (O2EM)",
    "pcsx_rearmed": "Sony - PlayStation (PCSX ReARMed)",
    "picodrive": "Sega - MS/GG/MD/CD/32X (PicoDrive)",
    "pokemini": "Nintendo - Pokemon Mini (PokeMini)",
    "prosystem": "Atari - 7800 (ProSystem)",
    "puae": "Commodore - Amiga (PUAE)",
    "snes9x2010": "Nintendo - SNES / SFC (Snes9x 2010)",
    "vecx": "GCE - Vectrex (vecx)",
    "vice_x64": "Commodore - C64 (VICE x64, fast)",
}


def gamelist_names(folder):
    # Regex instead of an XML parser: these files come from untrusted vendor cards.
    names = {}
    path = os.path.join(folder, "gamelist.xml")
    if os.path.isfile(path):
        text = open(path, encoding="utf-8", errors="replace").read()
        for block in re.findall(r"<game\b.*?</game>", text, re.S):
            p = re.search(r"<path>(.*?)</path>", block, re.S)
            n = re.search(r"<name>(.*?)</name>", block, re.S)
            if p and n:
                # Vendor names carry a sort prefix such as "0511 10-Yard Fight".
                name = re.sub(r"^\d{3,5}\s+", "", html.unescape(n.group(1).strip()))
                names[os.path.normpath(html.unescape(p.group(1).strip()))] = name
    return names


def clean(name):
    # Corrupted FAT entries show up as control characters or replacement glyphs.
    return name.isprintable() and "�" not in name


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("roms", help="the ROMS partition, e.g. /Volumes/ROMS")
    p.add_argument("--mount", default="/storage/roms/ROMS", help="where Lakka mounts it")
    a = p.parse_args()

    playlists = {}
    for folder, (name, core, exts, use_gamelist) in SYSTEMS.items():
        root = os.path.join(a.roms, folder)
        if not os.path.isdir(root):
            continue
        exts = {"." + e for e in exts.split()}
        labels = gamelist_names(root) if use_gamelist else {}
        pl = playlists.setdefault(name, {"core": core, "items": []})
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and clean(d))
            for f in files:
                stem, ext = os.path.splitext(f)
                if f.startswith(".") or ext.lower() not in exts or not clean(f):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), a.roms)
                label = labels.get(os.path.normpath(os.path.relpath(os.path.join(dirpath, f), root)), stem)
                pl["items"].append({
                    "path": f"{a.mount}/{rel}",
                    "label": label,
                    "core_path": "DETECT",
                    "core_name": "DETECT",
                    "crc32": "DETECT",
                    "db_name": f"{name}.lpl",
                })

    out = os.path.join(a.roms, "playlists")
    os.makedirs(out, exist_ok=True)
    total = 0
    for name, pl in sorted(playlists.items()):
        if not pl["items"]:
            continue
        pl["items"].sort(key=lambda i: i["label"].lower())
        doc = {
            "version": "1.5",
            "default_core_path": f"{CORES}/{pl['core']}_libretro.so",
            "default_core_name": CORE_NAMES[pl["core"]],
            "label_display_mode": 0,
            "right_thumbnail_mode": 0,
            "left_thumbnail_mode": 0,
            "sort_mode": 0,
            "items": pl["items"],
        }
        with open(os.path.join(out, f"{name}.lpl"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        total += len(pl["items"])
        print(f"{len(pl['items']):6}  {name}")
    print(f"{total:6}  games in {out}")


if __name__ == "__main__":
    main()
