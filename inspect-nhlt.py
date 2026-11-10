#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the BABYTIGER endpoints in a live or saved ACPI NHLT table."""

import struct
import sys
from pathlib import Path

ACPI_HEADER_SIZE = 36
ENDPOINT_HEADER_SIZE = 23
LINK_DMIC = 2
LINK_SSP = 3
DEVICE_I2S = 4
RENDER = 0
CAPTURE = 1
EXPECTED_I2S = {(1, RENDER), (1, CAPTURE), (5, RENDER)}


def check_nhlt(path):
    table = path.read_bytes()
    if len(table) <= ACPI_HEADER_SIZE or table[:4] != b"NHLT":
        raise ValueError("missing NHLT header or endpoint count")
    if struct.unpack_from("<I", table, 4)[0] != len(table) or sum(table) % 256:
        raise ValueError("invalid NHLT length or checksum")

    offset = ACPI_HEADER_SIZE + 1
    i2s = set()
    dmic = False
    for _ in range(table[ACPI_HEADER_SIZE]):
        if offset + ENDPOINT_HEADER_SIZE > len(table):
            raise ValueError("truncated NHLT endpoint header")
        size = struct.unpack_from("<I", table, offset)[0]
        if size < ENDPOINT_HEADER_SIZE or offset + size > len(table):
            raise ValueError("invalid NHLT endpoint length")
        link_type = table[offset + 4]
        device_type, direction, bus = table[offset + 16 : offset + 19]
        if link_type == LINK_SSP and device_type == DEVICE_I2S:
            i2s.add((bus, direction))
        if link_type == LINK_DMIC and direction == CAPTURE:
            dmic = True
        offset += size

    print(f"NHLT I²S endpoints (SSP, direction 0=render/1=capture): {sorted(i2s)}")
    print(f"NHLT DMIC capture endpoint present: {dmic}")
    if i2s != EXPECTED_I2S or not dmic:
        raise ValueError("expected SSP1 render/capture, SSP5 render and DMIC capture")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        sys.exit(f"Usage: {sys.argv[0]} [NHLT_TABLE]")
    path = Path(sys.argv[1] if len(sys.argv) == 2 else "/sys/firmware/acpi/tables/NHLT")
    try:
        check_nhlt(path)
    except (OSError, ValueError) as exc:
        sys.exit(f"{path}: {exc}")
