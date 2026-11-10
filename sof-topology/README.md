# Patched Fedora stock SOF topology for BABYTIGER

This directory adds a compiled SOF IPC3 topology, its source patch and a reproducible builder to the machine-driver port.

The topology inserts a **read-only 180 Hz high-pass and fixed attenuation after the speaker volume control**. It uses the IIR EQ component found in Fedora's signed Apollo Lake firmware. Its calculated quantized linear peak bound is −20.18 dBFS, with a passband gain of approximately −27.79 dB. Those levels are conservative engineering choices for bench evaluation. Speaker power, supply voltage and gain-strap calibration on this hardware are still required.

The graph is

```
PCM0 -> user volume -> fixed high-pass/attenuation -> SSP5
```

The stock headset, digital microphone, HDMI and backend hardware-configuration blocks are byte-identical to Fedora's original topology. The builder verifies those invariants and rejects an unexpected input topology. It also preserves Fedora's manifest metadata while updating its element counts.

## Build

From this directory, on Fedora with the stock firmware package installed

```sh
sudo dnf install git python3 m4 patch alsa-lib alsa-sof-firmware
git clone --filter=blob:none https://github.com/thesofproject/sof.git sof-source
git -C sof-source fetch --depth=1 origin tag v2.2
python3 build-topology.py \
    --sof sof-source \
    --stock /usr/lib/firmware/intel/sof-tplg/sof-apl-da7219.tplg.xz \
    --output rebuilt-babytiger.tplg
sha256sum rebuilt-babytiger.tplg sof-apl-da7219-babytiger-bench.tplg
```

The output path must be new. The builder uses SOF v2.2 commit `57864296b07c5ffd673214dd5b1e3d07ee274a22`, exports the source to a temporary directory, applies the patch, generates the coefficient blob and compiles through ALSA's topology library. It requires Fedora's stock topology hash documented in VERIFICATION.txt.

The topology should have SHA-256

```
6770e3587d01c512b3de7a5f35dc122dd2bff89773b78721717d341f3b3cbeb1
```

## Staging and rollback

The following manual staging command adds the topology under its own name

```sh
sudo install -m 0644 sof-apl-da7219-babytiger-bench.tplg \
    /usr/lib/firmware/intel/sof-tplg/sof-apl-da7219-babytiger-bench.tplg
```

For an offline review or an authorized topology-load test, select the separate file with SOF's `snd_sof.tplg_filename=sof-apl-da7219-babytiger-bench.tplg` parameter on a one-time GRUB entry, alongside `snd_intel_dspcfg.dsp_driver=3`. If the SOF driver loads from the initramfs, include the file there by rebuilding that target initramfs. Confirm the loaded topology filename in the journal. The earlier machine-driver port continues to block SSP5 stream startup. A topology-load test can establish whether the new component registers before any speaker stream is attempted.

For rollback, omit that one-time topology parameter and remove the separately staged file. If you included it in the initramfs, regenerate the target image after removing it. The machine-driver installation and rollback scripts in the parent directory cover the module override.

## What this implements

Fedora's signed SOF v2.2 APL image contains the EQIIR UUID. The DRC and multiband DRC UUIDs are absent, so a topology referencing those algorithms would require another firmware image. The implemented IIR stage has immutable coefficients through the normal ALSA control interface and runs after the user-adjustable gain. It reduces low-frequency output and places a fixed digital bound on the signal in the mathematical model.

ChromeOS's three-band compressor remains absent. Its gain choices have not been calibrated against the CX1500CNA speakers. The standalone tests exercised the exact upstream generic fixed-point IIR implementation, including a full-scale adversarial sequence, but the DSP's HiFi3 implementation and physical amplifier have not been exercised. See [VERIFICATION.txt](VERIFICATION.txt).

The original requirement for speaker safety remains unresolved at the physical-output stage. A measured load test, gain-chain calibration and checks on the actual speaker assembly are necessary before recommending built-in speaker playback.
