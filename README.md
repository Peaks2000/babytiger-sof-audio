# BABYTIGER SOF audio port for Fedora 45

Experimental port. Live BABYTIGER routing matches the port. Physical speaker safety verification is pending.

Target kernel **7.3.3-300.fc45.x86_64**, ASUS Chromebook CX1500CNA with MrChromebox Full ROM. This is an experimental headset and microphone port. **Keep the internal speakers disabled.** The patch preserves the topology’s SSP5 backend and binds the standard MAX98357A codec driver, but disables its speaker DAPM endpoint and rejects stream startup on that backend with `-EPERM`. There is no runtime enable switch.

## Stock SOF topology patch

The follow-up [SOF topology patch](sof-topology/README.md) includes a compiled
APL topology with fixed, read-only speaker high-pass filtering and attenuation,
plus its source patch and reproducible builder. Its offline digital tests and
hardware limitations are documented there.

## Simple installer

Run `./install.sh --check` to check the target system and development files.
Run `./install.sh` as your normal user to build, then install the module through
sudo. The module keeps SSP5 playback blocked while speaker verification is
pending. Use `./install.sh --rollback` to restore the packaged module.

For the next verification step, transfer this directory to the Chromebook and
run `sudo ./collect-diagnostics.sh` through its local terminal or RustDesk
terminal. The resulting private `diagnostics/` directory contains the live
NHLT table and audio state. Review it before sharing and keep it out of Git.

## What the sources establish

- Fedora’s Apollo Lake ACPI table already matches `DLGS7219` with `MX98357A`, requests `bxt_da7219_mx98357a`, and selects `sof-apl-da7219.tplg`. The target kernel’s SOF DA7219 driver lacks the matching platform ID. The patch adds it and leaves the PCI DSP-selection and AVS drivers alone. See `sound/soc/intel/common/soc-acpi-intel-bxt-match.c` and `sound/soc/intel/boards/sof_da7219.c` in the [Fedora source RPM](https://kojipkgs.fedoraproject.org/packages/kernel/7.3.3/300.fc45/src/kernel-7.3.3-300.fc45.src.rpm).
- MrChromebox’s CORAL source identifies BABYTIGER as SKUs 30 and 33 and inherits the REEF NHLT initializer. It declares DA7219 capture and playback on SSP1, MAX98357A playback on SSP5, and a two-channel DMIC configuration. The CORAL UEFI build includes NHLT blobs. The device tree assigns DA7219 to I²C address `0x1a`, and describes the MAX98357A as an I²S amplifier with active-high SD_MODE on GPIO 76. This is firmware-source evidence. The user’s live NHLT output confirms the expected port set. GPIO state and audio behavior still need verification on the unit. [BABYTIGER SKU source](https://github.com/MrChromebox/coreboot/blob/771cde3579cc1bec8bad54c23267894c6a1b2d29/src/mainboard/google/reef/variants/coral/mainboard.c), [NHLT initializer](https://github.com/MrChromebox/coreboot/blob/771cde3579cc1bec8bad54c23267894c6a1b2d29/src/mainboard/google/reef/variants/baseboard/nhlt.c), [device tree](https://github.com/MrChromebox/coreboot/blob/771cde3579cc1bec8bad54c23267894c6a1b2d29/src/mainboard/google/reef/variants/baseboard/devicetree.cb), [UEFI config](https://github.com/MrChromebox/coreboot/blob/771cde3579cc1bec8bad54c23267894c6a1b2d29/configs/apl/config.coral.uefi).
- I decoded Fedora 45’s shipped topology. It uses SSP5 as BE 0, SSP1 as BE 1, `dmic01` as BE 2, and iDisp as BEs 3–5. The corresponding PCM devices are Speakers 0, Headset 1, DMIC 99, and HDMI 5–7. The port uses a single DMIC backend, preserves the DA7219 jack setup, and keeps Fedora’s topology-derived DA7219 MCLK and PLL SRM handling. Probe requires BABYTIGER DMI, the two expected codecs, and a live I²S NHLT mask of exactly `0x22`. The mask checks port presence. The codec-to-port assignment comes from the CORAL firmware source. [Fedora SOF firmware package](https://packages.fedoraproject.org/pkgs/alsa-sof-firmware/alsa-sof-firmware/), [SOF topology format](https://github.com/thesofproject/sof-docs/blob/master/developer_guides/topology/topology.rst).
- The [SNAPPY repository](https://github.com/neilgbp/chromebook-snappy-audio-fix/tree/96afec1c27f86c078f7c1031b4980f81f54d0032) supplied the approach of matching the BXT platform and keeping the APL topology’s backend order. Its Ubuntu module failed on Fedora’s opaque DAPM context, obsolete link helper structure, and unquoted symbol namespaces. This port starts from Fedora’s implementation, including `snd_soc_dapm_to_card()`, `snd_soc_component_to_dapm()`, link-local codec callbacks, and quoted namespace imports. Each probe gets its own card instance.

## Build

Run these commands from the extracted bundle directory on Fedora 45. You can build while booted into another kernel. The Makefile rejects a different development tree and requires `Module.symvers`.

```sh
krel=7.3.3-300.fc45.x86_64
sudo dnf install "kernel-devel-$krel" gcc make elfutils-libelf-devel
make W=1
modinfo -F vermagic module/snd-soc-sof_da7219.ko
modinfo -F alias module/snd-soc-sof_da7219.ko
```

If DNF no longer offers this exact `kernel-devel`, get the matching Fedora RPM from the [Fedora build directory](https://kojipkgs.fedoraproject.org/packages/kernel/7.3.3/300.fc45/x86_64/) or a Fedora mirror. Prefer the signed Fedora RPM and verify it with `rpmkeys --checksig` before installing. For a development RPM extracted into a scratch directory, pass `make KDIR=/absolute/path/to/usr/src/kernels/$krel W=1`. Kbuild may skip BTF if the matching `vmlinux` is absent. An exact `vmlinux` with BTF can be extracted from Fedora’s matching `kernel-core` image using the kernel’s `scripts/extract-vmlinux` and placed in a writable copy of the development tree.

For an in-tree build, apply `0001-asoc-intel-sof-da7219-babytiger.patch` with `git apply` at the root of the exact Fedora source tree after applying the SRPM’s `patch-7.3-redhat.patch`. The out-of-tree `module/` includes the patched source and required private headers from that tree. The include path for the DA7219 header is local in this copy.

## Manual installation and test boot

1. Keep a stock fallback kernel available in GRUB. Boot the target kernel and collect the current board, ACPI and driver state before changing anything.

   ```sh
   uname -r
   cat /sys/class/dmi/id/{sys_vendor,product_name,board_name,product_sku,bios_version}
   lspci -nnk -d 8086:5a98
   sudo python3 ./inspect-nhlt.py
   ls -d /sys/bus/acpi/devices/{DLGS7219:00,MX98357A:00}
   cat /proc/cmdline
   modprobe -c | grep -E 'dsp_driver|avs.*max98357'
   ```

2. Keep the AVS speaker blacklist in place. To test SOF, use `snd_intel_dspcfg.dsp_driver=3` in a **one-time GRUB edit** for the target boot entry. Replace any existing `snd_intel_dspcfg.dsp_driver` argument in that entry. Fedora's kmod 34.2 appends the boot argument after any `options snd_intel_dspcfg dsp_driver=4` setting from modprobe.d, so the temporary boot uses SOF. The port expects the stock `sof-apl.ri` and `sof-apl-da7219.tplg` files and the installed UCM files. [Fedora kmod package](https://packages.fedoraproject.org/pkgs/kmod/kmod/fedora-45.html) · [kmod 34.2 configuration parser](https://github.com/kmod-project/kmod/blob/v34.2/libkmod/libkmod-config.c)
3. With Secure Boot or module signature enforcement, sign the built module using the target development tree’s `scripts/sign-file` and a key trusted by the running kernel. For example, from this bundle directory run `/usr/lib/modules/7.3.3-300.fc45.x86_64/build/scripts/sign-file sha256 /path/to/private-key /path/to/certificate.der module/snd-soc-sof_da7219.ko`. Check that the certificate is enrolled and confirm the signer with `modinfo -F signer`. The module produced by `make` is unsigned.
4. Install by hand from this bundle. The installer checks the release, board, live NHLT endpoint directions, ACPI device presence, and module metadata. It stages the override under `updates/babytiger`, runs `depmod`, and rebuilds the target’s standard Fedora initramfs via `dracut`. It preserves the packaged module and uses the existing Fedora boot entry. The script does not load or unload any modules or reboot.

   ```sh
   sudo ./install.sh module/snd-soc-sof_da7219.ko
   modinfo -k "$(uname -r)" -n snd_soc_sof_da7219
   ```

5. Reboot manually with the one-time SOF argument. Check the journal for the selected firmware and topology, `NHLT device I2S` with mask `0x22`, and machine driver errors. Check the platform device’s driver link before looking at userspace profiles.

   ```sh
   lspci -nnk -d 8086:5a98
   cat /sys/module/snd_intel_dspcfg/parameters/dsp_driver
   journalctl -k -b | grep -Ei 'sof|da7219|NHLT|98357'
   ls -l /sys/bus/platform/devices/bxt_da7219_mx98357a*/driver
   aplay -l
   arecord -l
   ```

   Confirm that the SOF card lists Headset PCM 1 and DMIC PCM 99 before trying those devices. If desktop audio is missing, the previous AVS UCM profile may not match the new SOF card. Use `alsaucm listcards` and verify that any SOF profile maps headphones to device 1 and the internal mic to device 99. For a raw ALSA headset check, first verify the card number in `aplay -l`, set a low headset volume using the **headset** control, plug in headphones, then play a short, quiet recording using `aplay -D plughw:N,1 file.wav` with the actual card number in place of `N`. The topology can still list a Speakers PCM because it defines the frontend. It is intentionally unavailable for playback.

## Rollback

From this bundle on Fedora 45, including when booted into a fallback kernel with the target still installed:

```sh
sudo ./rollback.sh
modinfo -k 7.3.3-300.fc45.x86_64 -n snd_soc_sof_da7219
```

The selected path should again point into the packaged `kernel/` subtree. Rollback removes the bundle’s override, regenerates the module index and rebuilds the target initramfs. Reboot without the one-time SOF argument. If you manually edited a persistent DSP setting, restore your original setting and rebuild the target initramfs with `sudo dracut --force --kver 7.3.3-300.fc45.x86_64`. AVS speaker blocking must remain in effect.

## Speaker protection

The decoded APL speaker graph runs PCM 0 through the writable `1 Master Playback Volume` PGA into SSP5. The control reaches 0 dB and the graph contains no EQ, compressor or limiter. The MAX98357A’s pin-selected gain and amplifier IC thermal protection provide no assurance about the speaker’s voice-coil temperature or cone excursion. A desktop volume cap or a low test volume provides no bound on every path to the amp. [Analog Devices MAX98357A data sheet](https://www.analog.com/en/products/max98357a.html).

BABYTIGER’s own ChromeOS board package contains a `speaker_eq` CRAS pipeline with three-band compression, a 180 Hz high-pass filter, and other EQ. The matching CRAS volume curve tops out at −7.5 dB, and ChromeOS UCM selects the DSP pipeline for its Speaker device. These are board-specific settings for the ChromeOS audio stack. Before enabling speakers on Fedora, establish the speaker assembly limits, amplifier gain strap and supply voltage on the CX1500CNA revision. A candidate SOF IPC3 graph would need a fixed output ceiling after user gain, validated filtering and time-dependent power limiting on every SSP5 playback path, and support for those components in the actual signed APL firmware. Check the complete gain chain and verify peak and sustained output with an instrumented load before connecting the speakers. Copying CRAS coefficients alone cannot establish those limits. [BABYTIGER ChromeOS DSP configuration](https://chromium.googlesource.com/chromiumos/overlays/board-overlays/+/6fa83c573487bbf90af92c0eb3444ff487db7c5f/overlay-coral/chromeos-base/chromeos-bsp-coral/files/babytiger/audio/cras-config/dsp.ini), [CRAS volume curve](https://chromium.googlesource.com/chromiumos/overlays/board-overlays/+/6fa83c573487bbf90af92c0eb3444ff487db7c5f/overlay-coral/chromeos-base/chromeos-bsp-coral/files/babytiger/audio/cras-config/bxtda7219max), [Chrultrabook AVS warning](https://docs.chrultrabook.com/docs/installing/installing-linux).

See [BUILD-VERIFICATION.txt](BUILD-VERIFICATION.txt) for the build and offline checks. Module insertion, SOF card registration, DA7219 clocks, jack routing, microphone channels, suspend and resume, and SD_MODE behavior remain untested on the physical Chromebook.

## Reproducing the checks

With SOF v2.2 available in a local Git repository, run

```sh
python3 tests/test-installer.py
python3 tests/test-filter.py --sof /path/to/sof
```

The installer tests use temporary paths and mock system commands. The filter
test compiles the upstream generic IIR with GCC and undefined-behavior checks
that trap on failure. See [SPEAKER-VALIDATION.md](SPEAKER-VALIDATION.md) for the
target's user-supplied diagnostics and the remaining physical checks.
