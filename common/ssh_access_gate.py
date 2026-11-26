#!/usr/bin/env python3
"""Install the boot gate for the SSH keys Cindy manages on a cloud computer into an image root.

Cindy on the machine keeps the owner's device keys in ~ubuntu/.ssh/cindy-owner-authorized-keys, the only
file sshd reads. A device revoked while the machine was off must not sign in before Cindy has rechecked the
device list, so at boot the gate sets a Cindy-written list aside before sshd accepts connections, and Cindy
writes it back after rechecking. If Cindy has not done so ten minutes after boot (it is not running), the
held list comes back so the owner can still sign in to repair the machine. A list someone maintains by hand
(no Cindy marker on its first line) is never touched.

Usage: ssh_access_gate.py ROOT   (ROOT is / on a running builder, or an offline image root)
"""

import os
from pathlib import Path
import sys

MARKER = "# Managed by Cindy SSH access; manual edits are overwritten."
GATE_PATH = "usr/local/lib/cindy-cloud-ssh/gate"

GATE = f"""#!/bin/bash
# Boot gate for the SSH keys Cindy manages (see cindy-ssh-access-gate.service). Runs as ubuntu.
set -euo pipefail
keys="$HOME/.ssh/cindy-owner-authorized-keys"
held="$keys.held"
marker='{MARKER}'
[[ -d $HOME/.ssh && ! -L $HOME/.ssh ]] || exit 0
case ${{1:-}} in
  hold)
    [[ -f $keys && ! -L $keys ]] || exit 0
    [[ $(head -n 1 -- "$keys") == "$marker" ]] || exit 0
    # Replace whatever is at the held path, so a link there cannot redirect the move.
    rm -f -- "$held"
    mv -- "$keys" "$held"
    ;;
  release)
    [[ -f $held && ! -L $held ]] || exit 0
    if [[ -e $keys || -L $keys ]]; then rm -f -- "$held"; else mv -- "$held" "$keys"; fi
    ;;
  *)
    echo 'usage: gate hold|release' >&2
    exit 2
    ;;
esac
"""

UNITS = {
    "cindy-ssh-access-gate.service": f"""[Unit]
Description=Hold Cindy-managed SSH keys until Cindy rechecks the device list
DefaultDependencies=no
After=local-fs.target
Before=sockets.target ssh.socket ssh.service
ConditionPathExists=/home/ubuntu/.ssh/cindy-owner-authorized-keys
[Service]
Type=oneshot
User=ubuntu
ExecStart=/{GATE_PATH} hold
[Install]
WantedBy=sockets.target
""",
    "cindy-ssh-access-release.service": f"""[Unit]
Description=Restore Cindy-managed SSH keys that Cindy has not rechecked
ConditionPathExists=/home/ubuntu/.ssh/cindy-owner-authorized-keys.held
[Service]
Type=oneshot
User=ubuntu
ExecStart=/{GATE_PATH} release
""",
    "cindy-ssh-access-release.timer": """[Unit]
Description=Restore Cindy-managed SSH keys ten minutes after boot if Cindy has not rechecked them
[Timer]
OnBootSec=10min
[Install]
WantedBy=timers.target
""",
}

WANTS = {
    "sockets.target.wants": "cindy-ssh-access-gate.service",
    "timers.target.wants": "cindy-ssh-access-release.timer",
}


def _inside(root, path):
    """Refuses paths that leave the image root through a link."""
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    if parent.resolve() != parent or not path.is_relative_to(root):
        raise ValueError("Unexpected link in image root: %s" % path)


def _write(root, path, text, mode):
    _inside(root, path)
    if path.is_symlink():
        raise ValueError("Unexpected link in image root: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path.is_file() and path.read_text() == text):
        staged = path.with_name("." + path.name + ".new")
        staged.write_text(text)
        staged.chmod(mode)
        os.replace(staged, path)
    path.chmod(mode)


def install(root):
    root = Path(root).resolve()
    _write(root, root / GATE_PATH, GATE, 0o755)
    system = root / "etc/systemd/system"
    for name, text in UNITS.items():
        _write(root, system / name, text, 0o644)
    for wants, name in WANTS.items():
        link = system / wants / name
        target = "/etc/systemd/system/" + name
        _inside(root, link)
        if link.is_symlink() and os.readlink(link) == target:
            continue
        if link.exists() or link.is_symlink():
            raise ValueError("Unexpected file in image root: %s" % link)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    install(sys.argv[1])
