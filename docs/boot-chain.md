# GD10 (S905) boot chain notes

Findings from reviving one GD10 stick (S905, `gxbb_p200_1G_100M_RealtekWiFi`, 1 GB RAM) whose stock card shipped EmuELEC 3.9.

## SD card layout

| Offset | Content |
|---|---|
| 0x000 to 0x1BB | First 444 bytes of the Amlogic SD image (kept as is) |
| 0x1BE | MBR partition table |
| 0x200 | Boot image: 16 random bytes, then BL2 with an `@AML` header at 0x210 |
| 0xC200 | FIP table of contents (`0xAA640001`, serial `0x12345678`, extended "new fip" area at +0x400) |
| 0x10200 | bl30, Cortex-M3 power management firmware |
| 0x1C200 | bl301, board extension of bl30 |
| 0x20200 | bl31, ARM Trusted Firmware v1.0 (Jan 2016) |
| 0x34200 | bl33, U-Boot (`TEXT_BASE` 0x01000000) |
| 0x100000 | First partition |

FIP offsets are relative to the boot image start (0x200), so the TOC sits at image offset 0xC000.

## Digests checked by BL2

Every stage starts with a 64-byte `@AML` header (same layout as in [meson-tools](https://github.com/afaerber/meson-tools/blob/master/aml.h)) followed by a 32-byte SHA-256 at `digest_offset` 0x40. The stage types seen here have `encrypted` = 0 (no RSA), so a correct SHA-256 is all BL2 asks for.

**BL2 itself** (checked by the boot ROM):

```
sha256(hdr[0:0x40] + img[data_offset : data_offset + offset2])
```

**FIP stages** (checked by BL2, routine at 0xd9002b18 when BL2 runs at 0xd9001000): before hashing, BL2 copies the last 0x60 bytes of the stage in front of the payload, so the stored layout is `header | digest | payload[0x60:] | payload[0:0x60]` and

```
sha256(entry[0:0x40] + entry[size-0x60:size] + entry[0x60:size-0x60])
```

After that rotation the payload lands at its load address unchanged (U-Boot at 0x01000000). On a mismatch BL2 prints `aml log : SIG CHK : 503 for address 0x...` on the UART, then `reset...`, and the stick reboots in a loop. With no U-Boot running, HDMI is never enabled, which is the "No signal" symptom.

`tools/aml_fip.py` implements both checks and the reverse operation.

## What we tried

1. **Stock card**: BL2, bl30, bl301 and bl31 verified, bl33 (vendor U-Boot `2015.01-ga9e95621aa-dirty`, built 2023-05-18) failed its digest. No single bit flip explains it, and no reference copy of that build was found.
2. **Amlogic vendor U-Boot 2015.01** (hardkernel `odroidc2-v2015.01` tree, `gxb_p200_v1` config with the vendor environment copied in, NAND disabled because its blobs are empty in that tree): accepted by BL2, but HDMI never came up. It crashes before `preboot`, cause unknown without a UART.
3. **Mainline U-Boot v2024.01, p200 + HDMI console**: boots, shows its console on the TV, sees the SD card as `mmc 1`.
4. **EmuELEC 4.3 (Amlogic 3.14 kernel) from mainline U-Boot**: two traps found, the kernel still hangs.
   - `bootm <img> - <fdt>` drops the ramdisk of an Android boot image. Use `bootm <img> <img> <fdt>`.
   - 3.14 arm64 kernels need the device tree within 512 MB of the kernel start: set `fdt_high` and `initrd_high` to `0x20000000`, like the vendor environment does.
   - With both fixes HDMI goes dark when the kernel starts, but `/init` never runs: a hook in the initramfs that logs to every partition and forces a reboot never fired. The 3.14 kernel probably depends on state only the vendor U-Boot sets up. A serial console is the next step.
5. **Lakka 6.1 AMLGX (mainline Linux)** with `meson-gxbb-p200.dtb`: boots, HDMI, USB gamepads.

## Thermal shutdowns on mainline

Symptom: after 5 to 15 minutes the TV says "no cable", the green LED stays on, and only a power cycle brings the stick back. The journal shows `cpu-thermal: critical temperature reached` then `HARDWARE PROTECTION shutdown (Temperature too high)`: an orderly power off at the 110 C trip.

What a logger sampling sysfs every 2 s showed:

- `scpi-cpufreq` (legacy pre-1.0 SCP firmware) offers 100 MHz to **2016 MHz**, and `ondemand` happily runs at 2016 MHz. With no cap: 45 C to 110 C in 4.5 minutes.
- The `cpu-thermal` zone has passive (80 C), hot (90 C) and critical (110 C) trips, and its cooling maps point at the four CPUs, but no cpufreq cooling device is registered, so nothing is bound to the zone and it never throttles.
- The only cooling device is `devfreq-d00c0000.gpu` (Lima), not referenced by any map, so the Mali-450 stays at 744 MHz.
- Capping the CPU alone is not enough: with the CPU at 500 MHz for most of a 16-minute session, the SoC still reached 105 C.
- RetroArch's default *Performance (Managed)* CPU mode rewrites `scaling_max_freq`, so a one-time cap does not hold.

`lakka/gd10-thermal.sh` reapplies CPU and GPU caps every 2 s based on the zone temperature. A cleaner fix would be a device tree overlay adding the GPU to the cooling maps, plus a cpufreq cooling device for `scpi-cpufreq`.

## Serial console

A 3.3 V USB to TTL adapter (CP2102, CH340 or FT232) on the board's TX/RX/GND pads at 115200 8N1 shows BL2, U-Boot and kernel logs. Never connect VCC.
