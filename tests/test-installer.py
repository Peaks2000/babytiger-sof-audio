import os
import struct
import subprocess
import tempfile
from pathlib import Path

out = Path(__file__).resolve().parents[1]
krel = "7.3.3-300.fc45.x86_64"
with tempfile.TemporaryDirectory(prefix="babytiger-installer-test-") as temp:
    root = Path(temp)
    for directory in ("boot", "run/lock", f"usr/lib/modules/{krel}/kernel",
                      "etc/modprobe.d", "etc/dracut.conf.d", "speaker-lock",
                      "sys/class/dmi/id", "sys/firmware/acpi/tables",
                      "sys/bus/acpi/devices/DLGS7219:00", "sys/bus/acpi/devices/MX98357A:00"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "etc/os-release").write_text("ID=fedora\nVERSION_ID=45\n")
    dmi = root / "sys/class/dmi/id"
    for key, value in (("sys_vendor", "Google"), ("product_name", "Babytiger"),
                       ("board_name", "Coral"), ("product_sku", "sku30")):
        (dmi / key).write_text(value + "\n")
    image = root / f"boot/initramfs-{krel}.img"
    image.write_text("original")
    module_root = root / f"usr/lib/modules/{krel}"
    override = module_root / "updates/babytiger/snd-soc-sof_da7219.ko"
    fake_module = root / "test.ko"
    fake_module.write_text("mock")
    guard = root / "etc/modprobe.d/00-babytiger-speaker-lock.conf"
    dracut_conf = root / "etc/dracut.conf.d/90-babytiger-speaker-lock.conf"
    for config in ("modprobe.conf", "dracut.conf"):
        (root / "speaker-lock" / config).write_bytes((out / "speaker-lock" / config).read_bytes())
    script = (out / "manage-module.sh").read_text().replace("$EUID == 0", "0 == 0")
    for prefix in ("/boot/", "/run/", "/sys/", "/etc/", "/usr/lib/modules/"):
        script = script.replace(prefix, f"{root}{prefix}")
    (root / "manage-module.sh").write_text(script)
    parser = (out / "inspect-nhlt.py").read_text().replace("/sys/", f"{root}/sys/")
    (root / "inspect-nhlt.py").write_text(parser)

    def make_nhlt(amp_port):
        records = [(3, 4, 0, 1), (3, 4, 1, 1), (3, 4, 0, amp_port), (2, 1, 1, 0)]
        blob = bytearray(b"NHLT" + b"\0" * 32)
        blob.append(len(records))
        for link, dev, direction, port in records:
            ep = bytearray(23)
            struct.pack_into("<I", ep, 0, len(ep))
            ep[4] = link
            ep[16:19] = bytes((dev, direction, port))
            blob.extend(ep)
        struct.pack_into("<I", blob, 4, len(blob))
        blob[9] = -sum(blob) % 256
        return blob

    nhlt = root / "sys/firmware/acpi/tables/NHLT"
    mocks = root / "mocks.sh"
    mocks.write_text("""
uname() { [[ $1 == -r ]] && echo "$KREL" || echo x86_64; }
modinfo() {
    if [[ $1 == -k ]]; then
        if [[ -f "$OVERRIDE" ]]; then echo "$OVERRIDE"; else echo "$STOCK"; fi
    else
        case "$2" in
            name) echo snd_soc_sof_da7219 ;;
            vermagic) echo "$KREL SMP" ;;
            alias) echo platform:bxt_da7219_mx98357a ;;
            babytiger_speaker_lock) echo "$LOCK_VERSION" ;;
        esac
    fi
}
depmod() { :; }
restorecon() { :; }
selinuxenabled() { return 1; }
dracut() { if [[ $FAIL == 1 ]]; then return 1; fi; printf rebuilt > "$1"; }
lsinitrd() {
    if [[ $1 == -f ]]; then
        [[ $FAIL != missing-lock ]] && cat -- "$GUARD"
    elif [[ $FAIL == amp-in-image ]]; then
        echo 'usr/lib/modules/test/kernel/sound/soc/codecs/snd-soc-max98357a.ko.xz'
    fi
    return 0
}
""")
    def run(action, expected, fail="0", lock_version="2"):
        args = [str(fake_module)] if action == "install" else []
        result = subprocess.run(["bash", str(root / "manage-module.sh"), action, *args],
                                env={**os.environ, "BASH_ENV": str(mocks), "KREL": krel,
                                     "OVERRIDE": str(override), "STOCK": str(module_root / "kernel/stock.ko"),
                                     "FAIL": fail, "LOCK_VERSION": lock_version, "GUARD": str(guard)},
                                capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr
        return result.stdout

    nhlt.write_bytes(make_nhlt(2))
    run("install", 1)
    assert not override.exists() and not guard.exists() and image.read_text() == "original"
    broken = make_nhlt(5)
    broken[-1] ^= 1
    nhlt.write_bytes(broken)
    run("install", 1)
    nhlt.write_bytes(make_nhlt(5))
    run("install", 1, lock_version="1")
    assert not guard.exists()
    dracut_conf.write_text("local configuration")
    run("install", 1)
    assert not guard.exists() and dracut_conf.read_text() == "local configuration"
    dracut_conf.unlink()
    run("install", 1, fail="1")
    assert not override.exists() and image.read_text() == "original"
    assert guard.read_bytes() == (out / "speaker-lock/modprobe.conf").read_bytes()
    assert dracut_conf.read_bytes() == (out / "speaker-lock/dracut.conf").read_bytes()
    for failure in ("missing-lock", "amp-in-image"):
        run("install", 1, fail=failure)
        assert not override.exists() and image.read_text() == "original"
    assert "snd_intel_dspcfg.dsp_driver=3" in run("install", 0)
    assert override.exists() and image.read_text() == "rebuilt"
    run("install", 1)
    run("rollback", 1, fail="1")
    assert override.exists() and image.read_text() == "rebuilt"
    assert "snd_intel_dspcfg.dsp_driver=3" not in run("rollback", 0)
    assert not override.exists()
    assert guard.exists() and dracut_conf.exists()
    run("rollback", 0)
    print("Scratch fixture checks passed for NHLT, lock, install, rollback, and initramfs failure handling.")
