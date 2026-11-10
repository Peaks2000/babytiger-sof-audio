#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Build a BABYTIGER SSP5 bench topology from Fedora's stock APL topology."""

import argparse
import cmath
import ctypes
import hashlib
import io
import math
import lzma
import struct
import subprocess
import tarfile
import tempfile
from pathlib import Path

SOF_COMMIT = "57864296b07c5ffd673214dd5b1e3d07ee274a22"
STOCK_HASH = "7e313f5e692494dc9bff62de18793736cea4ba45badca9716426f695b853093f"
HEADER = struct.Struct("<9I")
MANIFEST = (8, 0)
WIDGETS = (5, 1)
ROUTES = (4, 1)
PATCH = Path(__file__).with_name("0001-sof-apl-da7219-babytiger-eq.patch")
Q30 = 1 << 30


def impulse(a1, a2, numerator, length):
    values = []
    y1 = y2 = 0.0
    for i in range(length):
        y = (numerator[i] if i < 3 else 0.0) + a1 * y1 + a2 * y2
        values.append(y)
        y2, y1 = y1, y
    return values


def peak_bound(a1, a2, numerator):
    # The remainder after the first N terms is bounded by the envelope
    # of a damped sinusoid with the conjugate pole pair of this biquad.
    n = 4096
    pole = (a1 + cmath.sqrt(a1 * a1 + 4 * a2)) / 2
    radius, angle = cmath.polar(pole)
    if not 0 < radius < 1 or angle <= 0:
        raise ValueError("expected a stable, complex conjugate pole pair")
    response = impulse(a1, a2, numerator, n + 2)
    cos_term = response[n]
    sin_term = (response[n + 1] / radius - cos_term * math.cos(angle)) / math.sin(angle)
    tail = math.hypot(cos_term, sin_term) / (1 - radius)
    return sum(map(abs, response[:n])) + tail


def coefficients():
    # 48 kHz, second-order Butterworth high-pass. Apply attenuation to
    # the numerator before the feedback loop to leave internal headroom.
    omega = 2 * math.pi * 180 / 48000
    alpha = math.sin(omega) / math.sqrt(2)
    a1_q = round(2 * math.cos(omega) / (1 + alpha) * Q30)
    a2_q = round(-(1 - alpha) / (1 + alpha) * Q30)
    a1, a2 = a1_q / Q30, a2_q / Q30
    peak_at_unity = peak_bound(a1, a2, (1.0, -2.0, 1.0))
    b_q = math.floor(0.098 / peak_at_unity * Q30)
    b = b_q / Q30
    bound = peak_bound(a1, a2, (b, -2 * b, b))
    if bound >= 0.099:
        raise ValueError("quantized filter exceeds its design ceiling")
    print(f"48 kHz IIR passband at Nyquist: {20 * math.log10(4*b/(1+a1-a2)):.2f} dB")
    print(f"Quantized linear filter peak bound: {bound:.8f} ({20*math.log10(bound):.2f} dBFS)")
    print(f"Q2.30 feedback a2,a1 and feed-forward b2,b1,b0: {a2_q}, {a1_q}, {b_q}, {-2*b_q}, {b_q}")

    # SOF IPC3 user/eq.h. Two channels, one shared response, one biquad.
    words = (88, 2, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0,
             a2_q, a1_q, b_q, -2 * b_q, b_q, 0, 1 << 14)
    data = struct.pack("<22i", *words)
    # SOF ABI header, matching the upstream v2.2 IPC3 IIR template.
    return struct.pack("<4s7I", b"SOF\0", 0, len(data), 0x0300C000, 0, 0, 0, 0) + data


def compile_topology(directory, output):
    conf = output.with_suffix(".conf")
    with conf.open("wb") as config:
        subprocess.run(
            ["m4", "-I", "m4", "-I", "common", "-I", "platform/common",
             "sof-apl-da7219.m4"],
            cwd=directory, stdout=config, check=True,
        )

    lib = ctypes.CDLL("libatopology.so.2")
    lib.snd_tplg_new.restype = ctypes.c_void_p
    lib.snd_tplg_build_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.snd_tplg_free.argtypes = [ctypes.c_void_p]
    ctx = lib.snd_tplg_new()
    if not ctx:
        raise MemoryError("cannot create ALSA topology compiler")
    try:
        status = lib.snd_tplg_build_file(ctx, bytes(conf), bytes(output))
        if status:
            raise RuntimeError(f"libatopology failed with error {status}")
    finally:
        lib.snd_tplg_free(ctx)
    return output.read_bytes()


def blocks(data):
    result = {}
    offset = 0
    while offset < len(data):
        h = HEADER.unpack_from(data, offset)
        key = (h[3], h[7])
        end = offset + h[4] + h[6]
        if h[0] != 0x41536F43 or h[1] != 5 or h[4] != HEADER.size or end > len(data):
            raise ValueError("unexpected ALSA topology block header")
        if key in result:
            raise ValueError(f"duplicate block {key}")
        result[key] = data[offset:end]
        offset = end
    return result


def route_names(block):
    size = 3 * 44  # Three SNDRV_CTL_ELEM_ID_NAME_MAXLEN names.
    count = HEADER.unpack_from(block)[8]
    if len(block) != HEADER.size + size * count:
        raise ValueError("unexpected DAPM route block size")
    edges = set()
    for i in range(HEADER.size, len(block), size):
        fields = struct.unpack_from("44s44s44s", block, i)
        sink, control, source = (field.split(b"\0", 1)[0].decode() for field in fields)
        if control:
            raise ValueError("unexpected controlled route on the speaker graph")
        edges.add((source, sink))
    return edges


def merge(stock, baseline, candidate):
    stock, baseline, candidate = map(blocks, (stock, baseline, candidate))
    if stock.keys() != baseline.keys() or stock.keys() != candidate.keys():
        raise ValueError("unexpected topology block set")
    if any(stock[k] != baseline[k] for k in stock if k != MANIFEST):
        raise ValueError("rebuilt baseline differs from Fedora outside the manifest")
    if any(baseline[k] != candidate[k] for k in stock if k not in (MANIFEST, WIDGETS, ROUTES)):
        raise ValueError("the patch changed a non-speaker block")
    expected = {
        ("PCM0P", "BUF1.0"), ("BUF1.0", "PGA1.0"), ("PGA1.0", "BUF1.2"),
        ("BUF1.2", "EQIIR1.0"), ("EQIIR1.0", "BUF1.1"), ("BUF1.1", "SSP5.OUT"),
    }
    if route_names(candidate[ROUTES]) != expected:
        raise ValueError("missing or unexpected edge in the speaker pipeline")
    for key in stock:
        if key[0] == 4 and key != ROUTES:
            if b"SSP5.OUT\0" in stock[key] or b"EQIIR1.0\0" in stock[key]:
                raise ValueError("another pipeline routes to the SSP5 DAI or fixed EQ")

    manifest = bytearray(stock[MANIFEST])
    for key, offset in ((WIDGETS, 8), (ROUTES, 12)):
        old_count = HEADER.unpack_from(stock[key])[8]
        new_count = HEADER.unpack_from(candidate[key])[8]
        if new_count - old_count != 2:
            raise ValueError(f"unexpected element count change in {key}")
        offset += HEADER.size
        total = struct.unpack_from("<I", manifest, offset)[0]
        struct.pack_into("<I", manifest, offset, total + new_count - old_count)
    # The added EQ carries one embedded bytes control.
    control_offset = HEADER.size + 4
    controls = struct.unpack_from("<I", manifest, control_offset)[0]
    struct.pack_into("<I", manifest, control_offset, controls + 1)
    marker = candidate[WIDGETS].find(b"BABYTIGER SSP5 fixed EQ\0")
    if marker < 0 or struct.unpack_from("<I", candidate[WIDGETS], marker + 44)[0] != 1:
        raise ValueError("EQ coefficients must expose read access only")
    stock[MANIFEST] = bytes(manifest)
    stock[WIDGETS] = candidate[WIDGETS]
    stock[ROUTES] = candidate[ROUTES]
    return b"".join(stock.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sof", type=Path, required=True, help="SOF Git repository with tag v2.2")
    parser.add_argument("--stock", type=Path, required=True, help="Fedora APL topology, raw or .xz")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.stock.read_bytes()
    if args.stock.suffix == ".xz":
        data = lzma.decompress(data)
    if hashlib.sha256(data).hexdigest() != STOCK_HASH:
        parser.error("stock topology hash does not match the verified Fedora 45 package")
    with tempfile.TemporaryDirectory(prefix="babytiger-sof-") as temp:
        stage = Path(temp)
        archive = subprocess.check_output(
            ["git", "-C", str(args.sof), "archive", SOF_COMMIT, "tools/topology/topology1"]
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(stage, filter="data")
        source = stage / "tools/topology/topology1"
        baseline = compile_topology(source, stage / "baseline.tplg")
        subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(PATCH.resolve())],
                       cwd=source, check=True)
        blob = coefficients()
        byte_list = ",".join(f"0x{value:02x}" for value in blob)
        (source / "babytiger-eq-coefficients.m4").write_text(
            f'SectionData."babytiger_eq_data" {{\n    bytes "{byte_list}"\n}}\n'
        )
        candidate = compile_topology(source, stage / "candidate.tplg")
        output = merge(data, baseline, candidate)
        if blocks(output)[WIDGETS].count(blob) != 1:
            raise ValueError("fixed IPC3 coefficient blob is missing or duplicated")
    with args.output.open("xb") as target:
        target.write(output)
    print(f"{hashlib.sha256(output).hexdigest()}  {args.output}")


if __name__ == "__main__":
    main()
