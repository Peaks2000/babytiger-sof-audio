#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Run the SOF v2.2 generic fixed-point IIR on full-scale test inputs."""

import argparse
import ctypes
import importlib.util
import math
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("topology_builder", ROOT / "sof-topology/build-topology.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

HOST_FORMAT_HEADER = """
#include <stdint.h>
#include <limits.h>
#define Q_SHIFT_RND(x, src_q, dst_q) ((((x) >> ((src_q) - (dst_q) - 1)) + 1) >> 1)
static inline int32_t sat_int32(int64_t value)
{
    return value > INT32_MAX ? INT32_MAX : value < INT32_MIN ? INT32_MIN : value;
}
static inline int16_t sat_int16(int32_t value)
{
    return value > INT16_MAX ? INT16_MAX : value < INT16_MIN ? INT16_MIN : value;
}
static inline int32_t sat_int24(int32_t value)
{
    return value > 8388607 ? 8388607 : value < -8388608 ? -8388608 : value;
}
"""
HOST_HARNESS = """
#include <sof/audio/format.h>
#include <sof/math/iir_df2t.h>
#include <string.h>
int run_filter(const int32_t *coefficients, const int32_t *input,
               int16_t *output, unsigned int count)
{
    int32_t coef[7];
    memcpy(coef, coefficients, sizeof(coef));
    int64_t delay[2] = {0};
    struct iir_state_df2t filter = {1, 1, coef, delay};
    for (unsigned int i = 0; i < count; i++)
        output[i] = iir_df2t_s32_s16(&filter, input[i]);
    return 0;
}
"""


def compile_reference(sof, directory):
    files = {
        "src/math/iir_df2t_generic.c": "filter.c",
        "src/include/sof/math/iir_df2t.h": "sof/math/iir_df2t.h",
        "src/include/sof/math/iir_df2t_generic.h": "sof/math/iir_df2t_generic.h",
        "src/include/user/eq.h": "user/eq.h",
    }
    for source, target in files.items():
        content = subprocess.check_output(
            ["git", "-C", str(sof), "show", f"{builder.SOF_COMMIT}:{source}"]
        )
        path = directory / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    path = directory / "sof/audio/format.h"
    path.parent.mkdir(parents=True)
    path.write_text(HOST_FORMAT_HEADER)
    (directory / "harness.c").write_text(HOST_HARNESS)
    library = directory / "reference.so"
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
         "-Wno-sign-compare", "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
         "-I", str(directory), str(directory / "filter.c"),
         str(directory / "harness.c"), "-o", str(library)],
        check=True,
    )
    return ctypes.CDLL(str(library))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sof", type=Path, required=True)
    args = parser.parse_args()
    blob = builder.coefficients()
    topology = ROOT / "sof-topology/sof-apl-da7219-babytiger-bench.tplg"
    if topology.read_bytes().count(blob) != 1:
        raise ValueError("the tested coefficients must occur once in the shipped topology")
    coefficients = struct.unpack("<7i", blob[-28:])
    a2, a1, b2, b1, b0, shift, gain = coefficients
    if shift != 0 or gain != 16384:
        raise ValueError("unexpected IIR output gain")
    impulse = builder.impulse(
        a1 / builder.Q30, a2 / builder.Q30,
        (b0 / builder.Q30, b1 / builder.Q30, b2 / builder.Q30), 8192
    )

    count = 48000
    positive = (1 << 31) - 1
    negative = -(1 << 31)
    rng = random.Random(79)
    cases = {
        "positive DC": [positive] * count,
        "negative DC": [negative] * count,
        "alternating full scale": [negative, positive] * (count // 2),
        "random full scale": [rng.choice((negative, positive)) for _ in range(count)],
        "adversarial impulse-sign sequence": [
            positive if value >= 0 else negative for value in reversed(impulse)
        ],
        "stop after positive DC": [positive] * count + [0] * count,
    }
    for frequency in (20, 180, 1000, 10000):
        cases[f"sine {frequency} Hz"] = [
            round(positive * math.sin(2 * math.pi * frequency * i / 48000))
            for i in range(count)
        ]

    with tempfile.TemporaryDirectory(prefix="babytiger-filter-test-") as temp:
        reference = compile_reference(args.sof, Path(temp))
        pointer32 = ctypes.POINTER(ctypes.c_int32)
        reference.run_filter.argtypes = [
            pointer32, pointer32, ctypes.POINTER(ctypes.c_int16), ctypes.c_uint
        ]
        coef = (ctypes.c_int32 * 7)(*coefficients)
        for name, samples in cases.items():
            source = (ctypes.c_int32 * len(samples))(*samples)
            output = (ctypes.c_int16 * len(samples))()
            reference.run_filter(coef, source, output, len(samples))
            peak = max(map(abs, output))
            if peak > 3277:
                raise AssertionError(f"{name} exceeds -20 dBFS: {peak}/32768")
            print(f"{name}: {peak}/32768, {20 * math.log10(peak / 32768):.3f} dBFS")
    print("Generic fixed-point checks passed with undefined-behavior sanitizer enabled.")


if __name__ == "__main__":
    main()
