#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
umask 077
destination=${1:-diagnostics}
[[ ! -e "$destination" ]] || {
    printf 'Choose a new diagnostic directory. Existing path: %s\n' "$destination" >&2
    exit 1
}
mkdir -m 0700 -- "$destination"

# These commands inspect state. Each optional command records its own failure.
capture() {
    local name=$1
    shift
    "$@" >"$destination/$name.txt" 2>&1 || {
        printf 'Unavailable diagnostic: %s\n' "$name" >&2
    }
}

capture kernel uname -r
capture os cat /etc/os-release
capture board sh -c '
    for field in sys_vendor product_name board_name product_sku bios_version bios_date; do
        printf "%s=" "$field"
        cat "/sys/class/dmi/id/$field" || :
    done
'
capture pci lspci -nnk -d 8086:5a98
capture cards cat /proc/asound/cards
capture playback-devices aplay -l
capture capture-devices arecord -l
capture dsp-selection cat /sys/module/snd_intel_dspcfg/parameters/dsp_driver
capture module-config sh -c 'modprobe -c | grep -Ei "dsp_driver|avs.*max98357|sof.*tplg"'
capture firmware-package rpm -q alsa-sof-firmware alsa-ucm kernel-devel
capture codec-devices sh -c '
    for device in /sys/bus/acpi/devices/DLGS7219:* /sys/bus/acpi/devices/MX98357A:*; do
        test -d "$device" || continue
        printf "%s\n" "$device"
        cat "$device/status" || :
        readlink "$device/physical_node" || :
    done
'
if [[ -r /sys/firmware/acpi/tables/NHLT ]]; then
    cp -- /sys/firmware/acpi/tables/NHLT "$destination/NHLT.bin"
    capture nhlt python3 "$(dirname -- "$0")/inspect-nhlt.py" "$destination/NHLT.bin"
else
    printf 'NHLT needs elevated read permission. Re-run with sudo to include it.\n' >&2
fi
# Audio messages can contain device identifiers. Keep this directory private.
capture audio-journal sh -c 'journalctl -k -b --no-pager | grep -Ei "sof|da7219|98357|NHLT|snd_soc_avs"'
printf 'Saved diagnostic files in %s\n' "$destination"
printf 'Review these files before sharing. They are excluded from Git by .gitignore.\n'
