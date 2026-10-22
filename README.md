# gd10-revive

Bring a dead **GD10 "game stick"** (Amlogic S905, the HDMI retro sticks sold with "35 000 games") back to life, using mainline U-Boot and [Lakka](https://www.lakka.tv/) (RetroArch).

Typical symptom: the TV says **"No signal"**, the green LED is on, nothing else happens. On the stick we revived, the stock SD card was badly corrupted: about a third of the ROMs and the system image were unreadable, and the U-Boot copy on the card failed its checksum, so the boot ROM rebooted in a loop before ever lighting up HDMI.

## Is this your stick?

GD10 sticks ship with different chips. This project only supports the **S905 (GXBB)** variant. Check the `dtb.img` file on the first partition of the stock card:

```sh
strings dtb.img | head -1
# gxbb_p200_1G_100M_RealtekWiFi   <- supported (S905, "p200" reference design)
# gxl_p281_1g, gxl_p212_...      <- S905W/S905X/S905L: different bootloader, not supported yet
```

`tools/aml_fip.py verify` also prints the SoC family it finds in the bootloader.

## How it works

The S905 boots from the SD card: the boot ROM loads **BL2** from sector 1, BL2 initializes the RAM and then loads four more stages listed in a FIP table (BL30, BL301, BL31 and **BL33 = U-Boot**). BL2 checks a SHA-256 digest for every stage but there is **no signature**, so any U-Boot hashed the right way is accepted.

We keep the stock BL2 and BL3x (they carry the RAM timings of the board) and replace U-Boot with **mainline U-Boot v2024.01** built for the p200 reference board, with an HDMI console. That U-Boot boots the official Lakka AMLGX image, which uses a mainline Linux kernel and the `meson-gxbb-p200.dtb` device tree.

The full story, the SD card layout and the digest format BL2 checks are in [docs/boot-chain.md](docs/boot-chain.md).

## What you need

- macOS or Linux with Docker and Python 3
- an SD card reader
- a **new, genuine SD card** (16 GB or more). The stock cards are often fake-capacity or worn out.
- ideally the **stock SD card**, for its bootloader

## Build and flash

1. **Dump the first MiB of the stock card** (find its disk name with `diskutil list` or `lsblk`):
   ```sh
   sudo dd if=/dev/rdiskN of=stock-1MiB.bin bs=1m count=1     # macOS
   sudo dd if=/dev/sdX of=stock-1MiB.bin bs=1M count=1        # Linux
   ```
2. **Check it.** BL2, bl30, bl301 and bl31 must be `OK`. A `BAD` bl33 is expected: that is the broken U-Boot we replace.
   ```sh
   python3 tools/aml_fip.py verify stock-1MiB.bin
   ```
3. **Build the image.** Pass the size of the *new* card in bytes (`diskutil info diskN` or `lsblk -b`) to get a 4 GB system partition plus an exFAT `ROMS` partition you can fill from your computer. Leave `--card-bytes` out to let Lakka use the whole card instead.
   ```sh
   ./make-image.sh --dump stock-1MiB.bin --card-bytes 31299993600
   ```
   Add `--joypads-from stock-storage.img` to carry over the stock gamepad profiles (see below).
   No stock card, or a damaged BL2? Use the prebuilt bootloader from the [Releases](../../releases) page instead of `--dump`: `--bootloader gd10-s905-bootloader.bin`. It was taken from one GD10 and its RAM settings may not suit every board.
4. **Flash** `build/gd10-lakka.img` and format the ROMS partition. The script prints the exact commands.
5. **Boot.** You should see U-Boot, then Linux boot messages. The first boot creates the file systems and reboots once, then RetroArch starts.

## Gamepad profiles from the stock card

The vendor's EmuELEC setup ships RetroArch profiles for the bundled 2.4 GHz pads (DragonRise `0079:0006`, "Twin USB Gamepad" / "USB Gamepad" `0810:0001`, ShanWan "Twin USB Joystick" `20bc:5500`). Lakka reads the same format, so you can carry them over and get correct buttons on first boot.

1. Dump the stock card's second partition (Linux, about 2 GB):
   ```sh
   sudo dd if=/dev/rdiskNs2 of=stock-storage.img bs=4m status=progress   # macOS
   sudo dd if=/dev/sdX2 of=stock-storage.img bs=4M status=progress       # Linux
   ```
2. Add `--joypads-from stock-storage.img` to `make-image.sh`. You can also pass a folder of `.cfg` files instead.

The profiles are stored in `gd10/joypads` on the first partition and copied to `/storage/joypads/udev` by Lakka's first-boot script. Lakka merges that folder with its own profiles. To do it by hand on a running Lakka, copy the `.cfg` files from the stock card's `/joypads` folder into `/storage/joypads` over SSH or Samba.

## ROMs, BIOS and playlists

Put your games on the `ROMS` partition, one folder per system using the EmuELEC folder names (`nes`, `snes`, `genesis`, `psx`, ...), and BIOS files in `ROMS/bios`. RetroArch is preconfigured to look there.

Don't scan on the stick: RetroArch's scanner identifies files one by one, which takes hours on the S905 and heats it up. Build the playlists on your computer instead, then plug the card back in:

```sh
python3 tools/make_playlists.py /Volumes/ROMS     # or wherever the ROMS partition is mounted
```

It writes `ROMS/playlists` (where the image points RetroArch) with the right system names, for icons and thumbnails, and a default core per system. Arcade games get their full names from the stock `gamelist.xml` files. Run it again whenever you add games.

## Heat

On mainline Linux the S905's thermal zone has no working cooling device, and the firmware advertises CPU speeds up to 2 GHz. Left alone, the stick reaches the 110 C critical trip in 5 to 15 minutes and powers itself off. The image installs `gd10-thermal`, a small service that caps the CPU (1.3 GHz, then 1 GHz above 80 C, 500 MHz above 90 C) and the GPU (500, 285 then 125 MHz). It also sets RetroArch's CPU governing mode to *Balanced* instead of *Performance (Managed)*.

A small stick-on heatsink or some airflow around the stick still helps a lot.

## Input lag

Turn on your TV's game mode, then in RetroArch set *Settings > Latency > Max Swapchain Images* to 2 and *Hard GPU Sync* on (enable *Settings > User Interface > Show Advanced Settings* if you don't see them). *Run-Ahead* (1 frame) removes more lag on 8/16-bit systems but doubles the CPU load, so more heat.

## Known issues

- **Gamepads**: without the stock profiles, generic 2.4 GHz pads work but may have scrambled buttons. Fix it once with *Settings > Input > Port 1 Controls > Set All Controls*, then *Save Controller Profile*.
- **Wi-Fi**: the Realtek SDIO chip is probably not supported by the mainline kernel. Use a USB hub with an Ethernet adapter or copy files through the ROMS partition.
- **Performance**: the Mali-450 runs on the open source Lima driver, and the thermal caps slow things down further when the stick gets hot. 8/16-bit systems, arcade and PS1 are fine. PSP and Dreamcast are too heavy.
- **EmuELEC and other Amlogic 3.14 kernels do not boot** with mainline U-Boot (the kernel hangs before starting its initramfs). See [docs/boot-chain.md](docs/boot-chain.md) if you want to dig further with a serial console.

## Legal

No ROMs or BIOS files are distributed here. The prebuilt bootloader contains Amlogic firmware (BL2, BL30, BL301, BL31) extracted from a retail device, provided for repair and interoperability. U-Boot is GPL-2.0: the binary is built from upstream `v2024.01` plus [uboot/gd10.config](uboot/gd10.config) with [uboot/build.sh](uboot/build.sh). Lakka is downloaded from its official release and its checksum is verified.

## Credits

[U-Boot](https://source.denx.de/u-boot/u-boot), [Lakka](https://github.com/libretro/Lakka-LibreELEC) and LibreELEC, [meson-tools](https://github.com/afaerber/meson-tools) for the first description of the Amlogic image header, and [this write-up](https://www.tabnews.com.br/kevinjh07/meu-game-stick-gd10-veio-com-o-cartao-corrompido-e-reinstalar-o-sistema-me-ensinou-mais-sobre-boot-amlogic-do-que-eu-gostaria) about another GD10 with a corrupted card.

Scripts are under the [MIT license](LICENSE).
