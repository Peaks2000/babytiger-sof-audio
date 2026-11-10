Speaker validation is pending.

The user supplied terminal output from the target Chromebook on 10 November
2026. It identifies Fedora kernel 7.3.3-300.fc45.x86_64, product Babytiger,
baseboard Coral, SKU sku30, BIOS MrChromebox-2609.3, and PCI 8086:5a98.
The current driver is snd_soc_avs. Its configuration forces dsp_driver=4
and blacklists snd_soc_avs_max98357a.

The live NHLT parser reported 3,684 bytes, checksum zero and four endpoints.

| Endpoint | Link | Device type | Direction | Bus |
| --- | --- | --- | --- | --- |
| 0 | DMIC, type 2 | 0 | Capture | 0 |
| 1 | SSP, type 3 | I²S, type 4 | Playback | 1 |
| 2 | SSP, type 3 | I²S, type 4 | Capture | 1 |
| 3 | SSP, type 3 | I²S, type 4 | Playback | 5 |

This verifies that the target's exposed port set matches the port. Assignment
of DA7219 to SSP1 and MAX98357A to SSP5 is supported by the CORAL firmware
source. The terminal checks were run by the user through RustDesk.
They establish board identity and firmware routing.

The topology builder verifies that the added fixed IIR stage lies on every
topology route into SSP5 and that its coefficient control grants read access.
The exact upstream SOF generic fixed-point IIR was compiled and tested with
undefined-behavior instrumentation configured to trap. Tests include both
full-scale polarities, alternating samples, random samples, a sequence
constructed to maximize the filter output, sine waves and a stop transient.
The highest observed S16 magnitude was 3,211/32,768, approximately −20.176 dBFS.
The DSP's HiFi3 implementation has not been exercised.

The amplifier has a separate analog gain. Its data sheet gives a 2.1 dBV
reference and gain settings with tolerances up to 15.6 dB. Consequently the
digital sample limit alone cannot establish a speaker power limit on the
assembled Chromebook. Required physical evidence includes the actual gain
strap, supply voltage, speaker impedance and power/excursion ratings, and
measurement of the differential audio output and shutdown transitions.
[Analog Devices data sheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf)

The user has no oscilloscope, audio analyzer or dummy speaker load available.
There have been no speaker playback tests or output measurements. The shipped
machine-driver source blocks the speaker backend during stream startup.

Before enabling a speaker stream, the measurement setup must account for the
bridge-tied Class D output. Use an appropriate differential measurement and
audio filtering with a suitable dummy load. Establish board-specific limits
before testing the built-in speakers. The present evidence supports further
bench work. Physical speaker safety is still unverified.
