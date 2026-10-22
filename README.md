# gd10-revive

Bring a dead **GD10 "game stick"** (Amlogic S905, the HDMI retro sticks sold with "35 000 games") back to life, using mainline U-Boot and [Lakka](https://www.lakka.tv/) (RetroArch).

Typical symptom: the TV says **"No signal"**, the green LED is on, nothing else happens. On the stick we revived, the stock SD card was badly corrupted: part of the ROMs and the system image were unreadable, and the U-Boot copy on the card failed its checksum, so the boot ROM rebooted in a loop before ever lighting up HDMI.

Two guides below: **[A. you still have the stock card](#guide-a-you-still-have-the-stock-card)** (even a badly corrupted one), or **[B. starting from scratch](#guide-b-starting-from-scratch)** (no card, or nothing readable on it).

## Is this your stick?

GD10 sticks ship with different chips. This project only supports the **S905 (GXBB)** variant.

- **With the stock card**: look at `dtb.img` on its first partition.
  ```sh
  strings dtb.img | head -1
  # gxbb_p200_1G_100M_RealtekWiFi   <- supported (S905, "p200" reference design)
  # gxl_p281_1g, gxl_p212_...      <- S905W/S905X/S905L: different bootloader, not supported yet
  ```
- **Without it**: open the stick and read the main chip, it should say **S905** with no letter after it. Or simply try guide B: a card is cheap to reflash, and a stick that shows no U-Boot screen at all is either another variant or uses other RAM chips.

## How it works

The S905 boots from the SD card: the boot ROM loads **BL2** from sector 1, BL2 initializes the RAM and then loads four more stages listed in a FIP table (BL30, BL301, BL31 and **BL33 = U-Boot**). BL2 checks a SHA-256 digest for every stage but there is **no signature**, so any U-Boot hashed the right way is accepted.

We keep the stock BL2 and BL3x (they carry the RAM timings of the board) and replace U-Boot with **mainline U-Boot v2024.01** built for the p200 reference board, with an HDMI console. That U-Boot boots the official Lakka AMLGX image, which uses a mainline Linux kernel and the `meson-gxbb-p200.dtb` device tree. The image also installs gamepad profiles and a thermal throttle service (see [Heat](#heat)).

The full story, the SD card layout and the digest format BL2 checks are in [docs/boot-chain.md](docs/boot-chain.md).

## What you need

- macOS or Linux with Docker and Python 3, and an SD card reader
- a **new, genuine SD card**, 16 GB or more (32 GB leaves room for plenty of games). The stock cards are often fake-capacity or worn out: do not reuse them.

In the commands below, `diskN` (macOS) or `sdX` (Linux) is the card, found with `diskutil list` or `lsblk`. Double-check it: `dd` overwrites whatever you point it at.

## Guide A: you still have the stock card

Do steps 1 to 3 with the **stock card** in the reader, then switch to the **new card**.

1. **Back up its bootloader and check it.** BL2, bl30, bl301 and bl31 must be `OK`. A `BAD` bl33 is expected: that is the broken U-Boot we replace. If BL2 or a BL3x is `BAD`, use guide B instead.
   ```sh
   sudo dd if=/dev/rdiskN of=stock-1MiB.bin bs=1m count=1     # Linux: if=/dev/sdX bs=1M
   python3 tools/aml_fip.py verify stock-1MiB.bin
   ```
2. **Rescue your games.** The third partition of the stock card (`game` on ours) holds the ROMs. This copies everything readable, tests every archive, drops the corrupted ones and writes a `rescue.log`. A worn card reads at a few MB/s, so expect an hour or more; run it again to resume.
   ```sh
   python3 tools/rescue_roms.py /Volumes/game/roms ~/gd10-roms --skip psp
   ```
   `--skip psp` leaves out PSP games, which the S905 cannot run well and which take a lot of space.
3. **Optional: gamepad profiles from the card.** The image already ships the profiles of the usual GD10 pads (see [Gamepads](#gamepads)). If yours came with other pads, back up the second partition (Linux, about 2 GB) to carry its profiles over:
   ```sh
   sudo dd if=/dev/rdiskNs2 of=stock-storage.img bs=4m status=progress     # Linux: if=/dev/sdX2 bs=4M
   ```
4. **Build the image.** Put the new card in, read its exact size in bytes (`diskutil info diskN` or `lsblk -b`), and pass it to get a 4 GB system partition plus an exFAT `ROMS` partition you can fill from your computer:
   ```sh
   ./make-image.sh --dump stock-1MiB.bin --card-bytes 31299993600 [--joypads-from stock-storage.img]
   ```
5. **Flash and format.** The script prints the exact commands: a `dd` of `build/gd10-lakka.img` to the new card, then formatting its third partition as exFAT named `ROMS`.
6. **Copy the games and playlists** to the `ROMS` partition:
   ```sh
   cp -R ~/gd10-roms/* /Volumes/ROMS/
   dot_clean -m /Volumes/ROMS              # macOS only: removes the ._ files Finder leaves on exFAT
   python3 tools/make_playlists.py /Volumes/ROMS
   ```
   Keep `/*` in the `cp` command: on macOS, a source folder ending with `/` copies its content instead of the folder.
7. **Boot** (see [First boot](#first-boot)).

## Guide B: starting from scratch

1. **Get the prebuilt bootloader** from the [Releases](../../releases) page (`gd10-s905-bootloader.bin` and `SHA256SUMS`) and check it:
   ```sh
   shasum -a 256 -c SHA256SUMS      # Linux: sha256sum -c SHA256SUMS
   ```
   It holds the stock BL2/BL3x of one GD10 (S905, 1 GB RAM) plus the same mainline U-Boot as guide A. BL2 sets up the RAM, so if your stick uses different memory chips it will not boot at all (no U-Boot screen).
2. **Build the image.** With the new card in, read its exact size in bytes (`diskutil info diskN` or `lsblk -b`):
   ```sh
   ./make-image.sh --bootloader gd10-s905-bootloader.bin --card-bytes 31299993600
   ```
3. **Flash and format.** The script prints the exact commands: a `dd` of `build/gd10-lakka.img` to the card, then formatting its third partition as exFAT named `ROMS`.
4. **Add your games.** Create one folder per system at the root of `ROMS`, using the stock EmuELEC names listed in [docs/rom-folders.md](docs/rom-folders.md) (`nes`, `snes`, `genesis`, `gba`, `psx`, ...), and put BIOS files in `ROMS/bios`. Then build the playlists:
   ```sh
   python3 tools/make_playlists.py /Volumes/ROMS
   ```
5. **Boot** (see below).

## First boot

You should see U-Boot, then Linux boot messages and Lakka's "partition resizing" screen. The resize step fails on purpose (it would otherwise eat the `ROMS` partition), the system partition is created, and the stick reboots once. Then RetroArch starts with one playlist per system, gamepad profiles and the thermal service in place.

Plug the stick into a mains USB charger rather than the TV's USB port.

## Gamepads

The image ships the RetroArch profiles of the 2.4 GHz pads sold with GD10 sticks, taken from a stock EmuELEC card: DragonRise `0079:0006`, "Twin USB Gamepad" / "USB Gamepad" `0810:0001` and ShanWan "Twin USB Joystick" `20bc:5500` ([lakka/joypads](lakka/joypads)). They are installed on first boot, with or without a stock card.

`--joypads-from` adds the profiles found on a stock card (the second partition dumped in guide A, or a folder of `.cfg` files). They take precedence over the bundled ones.

Pad not covered? Map it once in RetroArch (*Settings > Input > Port 1 Controls > Set All Controls*, then *Save Controller Profile*) and send the resulting `.cfg` from `/storage/joypads` as a pull request so the next stick gets it too.

## Playlists

Don't scan on the stick: RetroArch's scanner identifies files one by one, which takes hours on the S905 and heats it up. `tools/make_playlists.py` writes `ROMS/playlists` (where the image points RetroArch) from your computer in a second, with the right system names, for icons and thumbnails, and a default core per system. Arcade games get their full names from the stock `gamelist.xml` files when present. Run it again whenever you add games.

## Heat

On mainline Linux the S905's thermal zone has no working cooling device, and the firmware advertises CPU speeds up to 2 GHz. Left alone, the stick reaches the 110 C critical trip in 5 to 15 minutes and powers itself off (HDMI goes dark, the LED stays on). The image installs `gd10-thermal`, a small service that caps the CPU (1.3 GHz, then 1 GHz above 80 C, 500 MHz above 90 C) and the GPU (500, 285 then 125 MHz). With it, our stick levels off around 80 to 82 C. It also sets RetroArch's CPU governing mode to *Balanced* instead of *Performance (Managed)*.

A small stick-on heatsink or some airflow around the stick still helps. To watch it, create a `gd10-debug` folder on the ROMS partition: the service then writes temperature and clock speeds to `gd10-debug/thermal.log` every 2 seconds. Delete the folder when done, the constant writes wear the card.

## Input lag

Turn on your TV's game mode, then in RetroArch set *Settings > Latency > Max Swapchain Images* to 2 and *Hard GPU Sync* on (enable *Settings > User Interface > Show Advanced Settings* if you don't see them). *Run-Ahead* (1 frame) removes more lag on 8/16-bit systems but doubles the CPU load, so more heat.

## Known issues

- **Wi-Fi**: the Realtek SDIO chip is probably not supported by the mainline kernel. Copy files through the ROMS partition.
- **Performance**: the Mali-450 runs on the open source Lima driver, and the thermal caps slow things down further when the stick gets hot. 8/16-bit systems, arcade and PS1 are fine. PSP and Dreamcast are too heavy.
- **EmuELEC and other Amlogic 3.14 kernels do not boot** with mainline U-Boot (the kernel hangs before starting its initramfs). See [docs/boot-chain.md](docs/boot-chain.md) if you want to dig further with a serial console.

## Legal

No ROMs or BIOS files are distributed here. The prebuilt bootloader contains Amlogic firmware (BL2, BL30, BL301, BL31) extracted from a retail device, provided for repair and interoperability. U-Boot is GPL-2.0: the binary is built from upstream `v2024.01` plus [uboot/gd10.config](uboot/gd10.config) with [uboot/build.sh](uboot/build.sh). Lakka is downloaded from its official release and its checksum is verified.

## Credits

[U-Boot](https://source.denx.de/u-boot/u-boot), [Lakka](https://github.com/libretro/Lakka-LibreELEC) and LibreELEC, [meson-tools](https://github.com/afaerber/meson-tools) for the first description of the Amlogic image header, and [this write-up](https://www.tabnews.com.br/kevinjh07/meu-game-stick-gd10-veio-com-o-cartao-corrompido-e-reinstalar-o-sistema-me-ensinou-mais-sobre-boot-amlogic-do-que-eu-gostaria) about another GD10 with a corrupted card.

Scripts are under the [MIT license](LICENSE).
