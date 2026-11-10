#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
umask 022

krel=7.3.3-300.fc45.x86_64
name=snd_soc_sof_da7219
filename=snd-soc-sof_da7219.ko
module_root=/usr/lib/modules/$krel
override=$module_root/updates/babytiger/$filename
image=/boot/initramfs-$krel.img
alias_name=platform:bxt_da7219_mx98357a
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
modprobe_lock=/etc/modprobe.d/00-babytiger-speaker-lock.conf
dracut_lock=/etc/dracut.conf.d/90-babytiger-speaker-lock.conf

die() { printf '%s\n' "$*" >&2; exit 1; }

# Keep these files across module rollback and failed initramfs builds.
check_lock_file() {
    local source=$1 destination=$2
    if [[ -e $destination || -L $destination ]]; then
        [[ -f $destination && ! -L $destination ]] && cmp -s -- "$source" "$destination" ||
            die "Unexpected existing configuration at $destination."
    fi
}

install_lock_file() {
    local source=$1 destination=$2 temporary
    [[ ! -f $destination ]] || return 0
    [[ -d ${destination%/*} ]] || install -d -m 0755 -- "${destination%/*}"
    temporary=$(mktemp -- "${destination%/*}/.babytiger-speaker-lock.XXXXXX")
    if ! install -m 0644 -- "$source" "$temporary" || ! mv -T -- "$temporary" "$destination"; then
        rm -f -- "$temporary"
        die "Could not install $destination."
    fi
    restorecon "$destination"
}

case "${1:-}" in
    install) [[ $# == 2 ]] || die 'Usage: install.sh PATH_TO_MODULE' ;;
    rollback) [[ $# == 1 ]] || die 'Usage: rollback.sh' ;;
    *) die 'Run install.sh or rollback.sh.' ;;
esac
action=$1

[[ $EUID == 0 ]] || die 'Run this script with sudo.'
. /etc/os-release
[[ $ID == fedora && $VERSION_ID == 45 && $(uname -m) == x86_64 ]] ||
    die 'This script requires Fedora 45 x86_64.'
[[ -d "$module_root/kernel" && -s "$image" && ! -L "$image" ]] ||
    die "Expected the installed stock kernel modules and standard Fedora initramfs for $krel."

exec 9>"/run/lock/babytiger-sof-$krel.lock"
flock -n 9 || die 'Another BABYTIGER module operation is running.'

if [[ $action == install ]]; then
    [[ $(uname -r) == "$krel" ]] || die "Boot $krel before installing."
    dmi=/sys/class/dmi/id
    vendor=$(<"$dmi/sys_vendor")
    product=$(<"$dmi/product_name")
    board=$(<"$dmi/board_name")
    sku=$(<"$dmi/product_sku")
    [[ $vendor == Google &&
        ( $product == Babytiger || $board == Babytiger ||
          ( $board == Coral && ( $sku == sku30 || $sku == sku33 ) ) ) ]] ||
        die 'BABYTIGER DMI check failed.'
    python3 "$repo/inspect-nhlt.py"
    [[ -e /sys/bus/acpi/devices/DLGS7219:00 && -e /sys/bus/acpi/devices/MX98357A:00 ]] ||
        die 'Expected DA7219 and MAX98357A ACPI devices.'
    module=$(realpath -e -- "$2")
    [[ -f "$module" && $(modinfo -F name "$module") == "$name" ]] ||
        die 'Unexpected module name.'
    [[ $(modinfo -F vermagic "$module") == "$krel "* ]] || die 'Module vermagic mismatch.'
    modinfo -F alias "$module" | grep -Fx "$alias_name" >/dev/null ||
        die 'The module is missing the Apollo Lake platform alias.'
    [[ $(modinfo -F babytiger_speaker_lock "$module") == 2 ]] ||
        die 'Expected the current BABYTIGER port with the amplifier disconnected.'
    if [[ -d /sys/firmware/efi ]]; then
        sb_state=$(LC_ALL=C mokutil --sb-state)
        if [[ $sb_state == *'SecureBoot enabled'* && -z $(modinfo -F signer "$module") ]]; then
            die 'Secure Boot is enabled. Sign the module with an enrolled key first.'
        fi
    fi
    selected=$(modinfo -k "$krel" -F filename "$name")
    [[ $selected == */modules/"$krel"/kernel/* && ! -e "$override" && ! -L "$override" ]] ||
        die 'Expected the stock module to be selected. Roll back any earlier override before installing.'

    check_lock_file "$repo/speaker-lock/modprobe.conf" "$modprobe_lock"
    check_lock_file "$repo/speaker-lock/dracut.conf" "$dracut_lock"
    install_lock_file "$repo/speaker-lock/modprobe.conf" "$modprobe_lock"
    install_lock_file "$repo/speaker-lock/dracut.conf" "$dracut_lock"
else
    if [[ ! -e "$override" && ! -L "$override" ]]; then
        printf 'No BABYTIGER module override is installed.\n'
        exit 0
    fi
    [[ -f "$override" && ! -L "$override" ]] || die 'Unexpected override file type.'
fi

# Work on the same filesystems as the paths that will be replaced.
stage=$(mktemp -d -- /boot/.babytiger-sof.XXXXXX)
module_tmp=
changed=0
cleanup() {
    local status=$?
    trap - EXIT
    if (( changed )); then
        if [[ $action == install ]]; then
            rm -f -- "$override" || status=1
        else
            mv -fT -- "$module_tmp" "$override" || {
                printf 'Restore the override from %s\n' "$module_tmp" >&2
                module_tmp=
                status=1
            }
        fi
        depmod -a "$krel" || { printf 'Re-run depmod for %s\n' "$krel" >&2; status=1; }
    fi
    [[ -z "$module_tmp" ]] || rm -f -- "$module_tmp"
    rm -rf -- "$stage"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

trap '' INT TERM
if [[ $action == install ]]; then
    install -d -m 0755 -- "${override%/*}"
    module_tmp=$(mktemp -- "${override%/*}/.module.XXXXXX")
    install -m 0644 -- "$module" "$module_tmp"
    mv -T -- "$module_tmp" "$override"
    changed=1
    restorecon "$override"
else
    module_tmp=$(mktemp -- "${override%/*}/.module.XXXXXX")
    mv -fT -- "$override" "$module_tmp"
    changed=1
fi
trap 'exit 130' INT
trap 'exit 143' TERM

depmod -a "$krel"
selected=$(modinfo -k "$krel" -F filename "$name")
if [[ $action == install ]]; then
    [[ $selected -ef $override ]] || die 'depmod did not select the BABYTIGER module.'
else
    [[ $selected == */modules/"$krel"/kernel/* ]] || die 'depmod did not select the stock module.'
fi

dracut "$stage/initramfs.img" "$krel"
if [[ -f $dracut_lock ]]; then
    lsinitrd -f "$modprobe_lock" "$stage/initramfs.img" | cmp -s -- "$modprobe_lock" - ||
        die 'The rebuilt initramfs is missing the speaker lock.'
    lsinitrd "$stage/initramfs.img" > "$stage/contents"
    if grep -Eq '/snd[-_]soc[-_](avs[-_])?max98357a\.ko(\.[[:alnum:]]+)?([[:space:]]|$)' "$stage/contents"; then
        die 'The rebuilt initramfs still contains a MAX98357A driver.'
    fi
fi
if selinuxenabled; then
    chcon --reference="$image" "$stage/initramfs.img"
fi
trap '' INT TERM
mv -fT -- "$stage/initramfs.img" "$image"
changed=0

printf 'Selected module for the next boot: %s\n' "$selected"
if [[ $action == install ]]; then
    printf '%s\n' 'Speaker lock installed for all kernels and included in the rebuilt target initramfs.'
    printf '%s\n' 'For the SOF test boot, set snd_intel_dspcfg.dsp_driver=3 in the temporary GRUB editor.'
    printf '%s\n' 'Replace any existing snd_intel_dspcfg.dsp_driver argument in that boot entry.'
fi
