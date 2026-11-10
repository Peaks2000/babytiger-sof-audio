#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
krel=7.3.3-300.fc45.x86_64
module=$repo/module/snd-soc-sof_da7219.ko

usage() {
    printf 'Usage: ./install.sh [--check | --build | --rollback | PATH_TO_MODULE]\n'
    printf 'Default: check Fedora and board, build the module, then install it using sudo.\n'
}
case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --rollback)
        [[ $# == 1 ]] || { usage >&2; exit 1; }
        if [[ $EUID == 0 ]]; then
            exec bash "$repo/manage-module.sh" rollback
        fi
        exec sudo bash "$repo/manage-module.sh" rollback
        ;;
esac
[[ $# -le 1 ]] || { usage >&2; exit 1; }
if [[ $# == 1 && $1 != --check && $1 != --build ]]; then
    [[ $1 != -* ]] || { usage >&2; exit 1; }
    if [[ $EUID == 0 ]]; then
        exec bash "$repo/manage-module.sh" install "$1"
    fi
    exec sudo bash "$repo/manage-module.sh" install "$1"
fi

. /etc/os-release
[[ $(uname -m) == x86_64 && ( ${1:-} == --build || ( $ID == fedora && $VERSION_ID == 45 ) ) ]] || {
    printf 'This installer targets Fedora 45 x86_64.\n' >&2
    exit 1
}
for command in gcc make python3 modinfo; do
    command -v "$command" >/dev/null || {
        printf 'Missing %s. Install gcc make python3 kmod and kernel-devel-%s.\n' "$command" "$krel" >&2
        exit 1
    }
done
if [[ ${1:-} != --build ]]; then
    [[ $(uname -r) == "$krel" ]] || {
        printf 'Boot %s before installing.\n' "$krel" >&2
        exit 1
    }
    vendor=$(</sys/class/dmi/id/sys_vendor)
    product=$(</sys/class/dmi/id/product_name)
    board=$(</sys/class/dmi/id/board_name)
    sku=$(</sys/class/dmi/id/product_sku)
    [[ $vendor == Google &&
        ( $product == Babytiger || $board == Babytiger ||
          ( $board == Coral && ( $sku == sku30 || $sku == sku33 ) ) ) ]] || {
        printf 'BABYTIGER DMI check failed.\n' >&2
        exit 1
    }
fi
kdir=${KDIR:-/usr/lib/modules/$krel/build}
[[ -s "$kdir/Module.symvers" ]] || {
    printf 'Install the matching development package: sudo dnf install kernel-devel-%s\n' "$krel" >&2
    exit 1
}
if [[ ${1:-} == --check ]]; then
    printf 'Build prerequisites, target kernel and BABYTIGER DMI match.\n'
    printf 'The installer checks the NHLT table with elevated read access during installation.\n'
    exit 0
fi

# Build with the invoking user's privileges. Use a normal shell for this step.
[[ $EUID != 0 ]] || {
    printf 'Run ./install.sh as your normal user. It invokes sudo for installation.\n' >&2
    exit 1
}
make -C "$repo" KDIR="$kdir" W=1
if [[ ${1:-} == --build ]]; then
    printf 'Built %s\n' "$module"
    exit 0
fi
exec sudo bash "$repo/manage-module.sh" install "$module"
