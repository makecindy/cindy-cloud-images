"""Seal a mounted, unbooted Ubuntu image for delivery. Never operates on the running root."""

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import shutil


def seal(root):
    root = root.resolve(strict=True)
    if root == Path("/"):
        raise ValueError("An offline image root is required")

    def checked(name):
        path = root / name
        if path.parent.resolve() != path.parent or path.is_symlink():
            raise ValueError("Unexpected image link: " + name)
        return path

    if (
        not checked("etc/systemd/user/cindy-cloud-host.service").is_file()
        and not checked("etc/systemd/user/cindy-cloud-desktop.service").is_file()
    ):
        raise ValueError("Prepared cloud runtime missing")
    owner = checked("home/ubuntu")
    for name in (
        ".local/share/keyrings",
        ".local/state/cindy-cloud",
        ".local/state/cindy-cloud-desktop",
        ".local/state/cindy-cloud-host",
        ".cindy",
        ".config/Cindy",
        ".config/CindyDev",
        ".config/google-chrome",
        ".cache/google-chrome",
        ".pki/nssdb",
        ".mozilla/firefox",
        "snap/firefox",
        ".ssh/cindy-owner-authorized-keys",
    ):
        if checked(str(owner.relative_to(root) / name)).exists():
            raise ValueError("User or enrollment material present in builder: " + name)
    identity_dir = checked("etc/cindy-cloud")
    snap_state = checked("var/lib/snapd/state.json")
    snap_keys = checked("var/lib/snapd/device/private-keys-v1")
    if snap_state.is_file():
        auth = json.loads(snap_state.read_text()).get("data", {}).get("auth", {})
        device = auth.get("device", {})
        if auth.get("users") or any(device.get(k) for k in ("key-id", "serial", "session-macaroon")):
            raise ValueError("Snap account or device registration is present")
    if snap_keys.exists() and any(snap_keys.iterdir()):
        raise ValueError("Snap device private keys are present")
    if identity_dir.exists() and any(
        entry.name.startswith((".instance-key.", ".enroll."))
        or entry.name in ("instance-key.pem", "enrollment.json")
        for entry in identity_dir.iterdir()
    ):
        raise ValueError("Guest enrollment is present")
    removals = [
        checked("root/.ssh/authorized_keys"),
        checked("home/ubuntu/.ssh/authorized_keys"),
        checked("var/lib/systemd/random-seed"),
        checked("var/log/cloud-init.log"),
        checked("var/log/cloud-init-output.log"),
    ]
    removals.extend(
        checked(str(p.relative_to(root)))
        for p in checked("etc/ssh").glob("ssh_host_*_key*")
    )
    machine_id = checked("etc/machine-id")
    dbus_id = root / "var/lib/dbus/machine-id"
    if dbus_id.parent.resolve() != dbus_id.parent:
        raise ValueError("Unexpected D-Bus directory")
    dbus_link = dbus_id.is_symlink()
    if dbus_link and os.readlink(dbus_id) not in (
        "/etc/machine-id",
        "../../../etc/machine-id",
    ):
        raise ValueError("Unexpected D-Bus machine-id link")
    cloud = checked("var/lib/cloud")
    for path in removals:
        path.unlink(missing_ok=True)
    if not dbus_link:
        dbus_id.unlink(missing_ok=True)
    if cloud.exists():
        shutil.rmtree(cloud)
    machine_id.write_text("uninitialized\n")


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    p.add_argument("--offline-root", required=True, type=Path)
    image = p.parse_args().offline_root.resolve(strict=True)
    if not image.is_mount() or image == Path("/"):
        p.error("Mount the powered-off clean builder image on a separate filesystem")
    seal(image)
