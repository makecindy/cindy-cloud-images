#!/usr/bin/env python3
"""Install a pinned, clean Cindy Host Linux release into an offline image root."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import sys

# Shipped next to this script on the builder; common/ in the repository.
for _dir in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent / "common"):
    if (_dir / "ssh_access_gate.py").is_file():
        sys.path.insert(0, str(_dir))
        break
import ssh_access_gate  # noqa: E402


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
        return result.hexdigest()


def install(release, root, expected, edition, arch):
    manifest = release / "SHA256SUMS.json"
    if (
        not re.fullmatch(r"[a-f0-9]{64}", expected)
        or manifest.is_symlink()
        or digest(manifest) != expected
    ):
        raise ValueError("Release inventory digest mismatch")
    inventory = json.loads(manifest.read_text())
    required = {"release.json", "cindy-host", "bin/host.mjs", "bin/node"}
    if not isinstance(inventory, dict) or not required <= inventory.keys():
        raise ValueError("Incomplete Host release")
    base = root / "opt/cindy-cloud-host"
    unit = root / "etc/systemd/user/cindy-cloud-host.service"
    for dest in (base, unit):
        if dest.resolve() != dest or not dest.is_relative_to(root):
            raise ValueError("Unexpected link in image root")
    base.mkdir(parents=True, exist_ok=True)
    target = base / expected
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        stage = Path(temporary) / "release"
        stage.mkdir()
        for name, checksum in inventory.items():
            parts = name.split("/")
            if any(part in ("", ".", "..") for part in parts) or not re.fullmatch(
                r"[a-f0-9]{64}", checksum
            ):
                raise ValueError("Invalid release inventory")
            origin = release / name
            if not origin.is_file() or any(
                path.is_symlink()
                for path in [origin, *origin.parents]
                if path.is_relative_to(release)
            ):
                raise ValueError("Unexpected link or special file in Host release")
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with origin.open("rb") as source, dest.open("xb") as out:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
            if digest(dest) != checksum:
                raise ValueError("Host release file digest mismatch")
            dest.chmod(0o755 if origin.stat().st_mode & 0o111 else 0o644)
        metadata = json.loads((stage / "release.json").read_text())
        if (metadata.get("region"), metadata.get("platform"), metadata.get("arch")) != (
            edition,
            "linux",
            arch,
        ):
            raise ValueError("Host release edition or architecture mismatch")
        for executable in ("cindy-host", "bin/node"):
            if not (stage / executable).stat().st_mode & 0o111:
                raise ValueError("Host launcher must be executable")
        if target.exists():
            paths = list(target.rglob("*"))
            if (
                target.is_symlink()
                or any(path.is_symlink() for path in paths)
                or {
                    str(path.relative_to(target)) for path in paths if not path.is_dir()
                }
                != set(inventory)
                or any(
                    not (target / name).is_file() or digest(target / name) != sha
                    for name, sha in inventory.items()
                )
            ):
                raise ValueError(
                    "Installed release does not match the pinned inventory"
                )
        else:
            os.rename(stage, target)
    script = root / "usr/local/lib/cindy-cloud-host/keyring"
    if script.resolve() != script:
        raise ValueError("Unexpected link in offline host image")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_bytes(Path(__file__).with_name("host-keyring.sh").read_bytes())
    script.chmod(0o755)
    ssh = root / "etc/ssh/sshd_config.d/00-cindy-cloud-owner.conf"
    ssh.parent.mkdir(parents=True, exist_ok=True)
    ssh.write_text(
        "AuthorizedKeysFile .ssh/cindy-owner-authorized-keys\nAuthorizedKeysCommand none\nPermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nExposeAuthInfo yes\n"
    )
    # Cindy keeps the owner's device keys in that file; recheck them at boot before sshd lets anyone in.
    ssh_access_gate.install(root)
    unit.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Unit]
Description=Cindy Cloud Host
ConditionUser=ubuntu
After=dbus.service
[Service]
WorkingDirectory=%h
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus
ExecStartPre=/usr/local/lib/cindy-cloud-host/keyring
ExecStartPre=/opt/cindy-cloud-host/{expected}/cindy-host login --cloud-guest
ExecStart=/opt/cindy-cloud-host/{expected}/cindy-host serve
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=default.target
"""
    if unit.exists() and unit.read_text() != content:
        raise ValueError("A different Host release is already installed")
    if not unit.exists():
        with unit.open("x") as out:
            out.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument(
        "--root", type=Path, required=True, help="Mounted clean Ubuntu image"
    )
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--edition", choices=["cn", "global"], required=True)
    parser.add_argument("--arch", choices=["x64", "arm64"], required=True)
    args = parser.parse_args()
    if args.root.resolve() == Path("/") or not (args.root / "etc/os-release").is_file():
        parser.error("Supply the mounted offline image root")
    tools = (
        "usr/bin/secret-tool",
        "usr/bin/gnome-keyring-daemon",
        "usr/bin/dbus-daemon",
        "usr/bin/openssl",
        "usr/bin/flock",
    )
    if any(not (args.root / name).is_file() for name in tools):
        parser.error(
            "Preinstall libsecret-tools, gnome-keyring, dbus-user-session, openssl and util-linux in the builder"
        )
    install(
        args.release.resolve(),
        args.root.resolve(),
        args.inventory_sha256,
        args.edition,
        args.arch,
    )
