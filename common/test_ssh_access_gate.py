import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ssh_access_gate  # noqa: E402


class SshAccessGateTest(unittest.TestCase):
    """Boot gate for the SSH keys Cindy manages: installed units and the hold/release script."""

    def test_install_writes_enabled_units_and_is_repeatable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            ssh_access_gate.install(root)
            ssh_access_gate.install(root)
            gate = root / ssh_access_gate.GATE_PATH
            self.assertEqual(gate.stat().st_mode & 0o777, 0o755)
            system = root / "etc/systemd/system"
            for name in ssh_access_gate.UNITS:
                self.assertEqual((system / name).stat().st_mode & 0o777, 0o644)
            self.assertIn("Before=sockets.target ssh.socket ssh.service", (system / "cindy-ssh-access-gate.service").read_text())
            self.assertIn("User=ubuntu", (system / "cindy-ssh-access-release.service").read_text())
            for wants, name in ssh_access_gate.WANTS.items():
                self.assertEqual(os.readlink(system / wants / name), "/etc/systemd/system/" + name)
            (system / "timers.target.wants/cindy-ssh-access-release.timer").unlink()
            (system / "timers.target.wants/cindy-ssh-access-release.timer").write_text("not a link")
            with self.assertRaises(ValueError):
                ssh_access_gate.install(root)

    def test_install_refuses_a_link_out_of_the_root(self):
        with TemporaryDirectory() as temporary, TemporaryDirectory() as outside:
            root = Path(temporary)
            (root / "usr/local").mkdir(parents=True)
            (root / "usr/local/lib").symlink_to(outside)
            with self.assertRaises(ValueError):
                ssh_access_gate.install(root)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_install_never_writes_through_a_link_beside_its_files(self):
        with TemporaryDirectory() as temporary, TemporaryDirectory() as outside:
            root = Path(temporary)
            victim = Path(outside) / "victim"
            victim.write_text("outside")
            victim.chmod(0o600)
            system = root / "etc/systemd/system"
            installed = [root / ssh_access_gate.GATE_PATH, *(system / name for name in ssh_access_gate.UNITS)]
            for path in installed:
                path.parent.mkdir(parents=True, exist_ok=True)
                # The staging name the first version of the installer used.
                path.with_name("." + path.name + ".new").symlink_to(victim)
            ssh_access_gate.install(root)
            self.assertEqual(victim.read_text(), "outside")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o600)
            for path in installed:
                self.assertFalse(path.is_symlink())
                self.assertTrue(path.is_file())

    def test_failed_install_leaves_no_staged_file(self):
        with TemporaryDirectory() as temporary:
            gate = Path(temporary) / ssh_access_gate.GATE_PATH
            gate.mkdir(parents=True)
            with self.assertRaises(OSError):
                ssh_access_gate.install(temporary)
            self.assertEqual(list(gate.parent.iterdir()), [gate])

    def gate(self, home, action, **env):
        script = home / "gate"
        script.write_text(ssh_access_gate.GATE)
        return subprocess.run(
            ["bash", str(script), action], env=dict(os.environ, HOME=str(home), **env), stderr=subprocess.PIPE, check=True
        )

    def test_holds_only_a_cindy_written_list_and_restores_it(self):
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            ssh = home / ".ssh"
            ssh.mkdir()
            keys = ssh / "cindy-owner-authorized-keys"
            held = ssh / "cindy-owner-authorized-keys.held"
            managed = ssh_access_gate.MARKER + "\nssh-ed25519 AAAA cindy-device:one\n"

            keys.write_text(managed)
            self.gate(home, "hold")
            self.assertFalse(keys.exists())
            self.assertEqual(held.read_text(), managed)
            self.gate(home, "release")
            self.assertEqual(keys.read_text(), managed)
            self.assertFalse(held.exists())

            # Cindy rechecked and wrote a new list but had not removed the held copy yet: keep the new list.
            self.gate(home, "hold")
            keys.write_text(ssh_access_gate.MARKER + "\n")
            self.gate(home, "release")
            self.assertEqual(keys.read_text(), ssh_access_gate.MARKER + "\n")
            self.assertFalse(held.exists())

            # A link left at the held path is replaced, not followed.
            elsewhere = home / "elsewhere"
            elsewhere.mkdir()
            held.symlink_to(elsewhere)
            self.gate(home, "hold")
            self.assertFalse(held.is_symlink())
            self.assertEqual(held.read_text(), ssh_access_gate.MARKER + "\n")
            self.assertEqual(list(elsewhere.iterdir()), [])
            self.gate(home, "release")
            self.assertEqual(keys.read_text(), ssh_access_gate.MARKER + "\n")

            # A list someone maintains by hand stays in force.
            keys.write_text("ssh-ed25519 AAAA laptop\n")
            self.gate(home, "hold")
            self.assertEqual(keys.read_text(), "ssh-ed25519 AAAA laptop\n")
            self.assertFalse(held.exists())

    def test_release_keeps_a_list_cindy_writes_back_meanwhile(self):
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            ssh = home / ".ssh"
            ssh.mkdir()
            keys = ssh / "cindy-owner-authorized-keys"
            held = ssh / "cindy-owner-authorized-keys.held"
            held.write_text(ssh_access_gate.MARKER + "\nssh-ed25519 AAAA cindy-device:revoked\n")
            rechecked = ssh_access_gate.MARKER + "\nssh-ed25519 AAAA cindy-device:kept\n"
            # Cindy writes the rechecked list after release has looked for it, just before the restore lands.
            tools = home / "bin"
            tools.mkdir()
            for tool in ("ln", "mv"):
                (tools / tool).write_text(f"#!/bin/sh\nprintf %s \"$RECHECKED\" > \"$KEYS\"\nexec '{shutil.which(tool)}' \"$@\"\n")
                (tools / tool).chmod(0o755)
            path = f"{tools}{os.pathsep}{os.environ['PATH']}"
            self.gate(home, "release", PATH=path, RECHECKED=rechecked, KEYS=str(keys))
            self.assertEqual(keys.read_text(), rechecked)
            self.assertFalse(held.exists())

    def test_ignores_a_linked_ssh_directory(self):
        with TemporaryDirectory() as temporary, TemporaryDirectory() as elsewhere:
            home = Path(temporary)
            target = Path(elsewhere)
            (target / "cindy-owner-authorized-keys").write_text(ssh_access_gate.MARKER + "\n")
            (home / ".ssh").symlink_to(target)
            self.gate(home, "hold")
            self.assertTrue((target / "cindy-owner-authorized-keys").exists())
            self.assertFalse((target / "cindy-owner-authorized-keys.held").exists())


if __name__ == "__main__":
    unittest.main()
