import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "seal_image", Path(__file__).with_name("seal-offline-image.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SealImageTest(unittest.TestCase):
    def test_retains_user_data_and_only_seals_clean_offline_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            def write(name, data="fixture"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
                return path

            write("etc/systemd/user/cindy-cloud-host.service")
            user = write("home/ubuntu/.config/Cindy/session")
            host_key = write("etc/ssh/ssh_host_ed25519_key")
            with self.assertRaises(ValueError):
                module.seal(root)
            self.assertTrue(user.exists() and host_key.exists())
            user.unlink()
            user.parent.rmdir()
            for name in (
                ".config/CindyGlobal/auto-update-settings.json",
                ".config/CindyDev/auto-update-settings.json",
                ".config/google-chrome/Default/History",
                ".cache/google-chrome/Default/Cache_Data/index",
                ".pki/nssdb/cert9.db",
                ".mozilla/firefox/profiles.ini",
                "snap/firefox/common/.mozilla/firefox/profiles.ini",
            ):
                browser_state = write("home/ubuntu/" + name)
                with self.assertRaisesRegex(ValueError, "User or enrollment material"):
                    module.seal(root)
                self.assertTrue(browser_state.exists() and host_key.exists())
                browser_state.unlink()
                parent = browser_state.parent
                while parent != root / "home/ubuntu" and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            snap_state = write("var/lib/snapd/state.json", '{"data":{"auth":{"device":{"key-id":"builder"}}}}')
            with self.assertRaisesRegex(ValueError, "Snap account or device"):
                module.seal(root)
            snap_state.write_text('{"data":{"auth":{"device":{"brand":"generic"}}}}')
            snap_key = write("var/lib/snapd/device/private-keys-v1/fixture")
            with self.assertRaisesRegex(ValueError, "Snap device private keys"):
                module.seal(root)
            self.assertTrue(host_key.exists())
            snap_key.unlink()
            for name in ("instance-key.pem", ".instance-key.leftover", ".enroll.leftover"):
                identity = write("etc/cindy-cloud/" + name)
                with self.assertRaisesRegex(ValueError, "Guest enrollment"):
                    module.seal(root)
                self.assertTrue(identity.exists())
                identity.unlink()
            cloud = write("var/lib/cloud/instances/test-id/user-data.txt")
            write("etc/machine-id")
            module.seal(root)
            self.assertEqual((root / "etc/machine-id").read_text(), "uninitialized\n")
            self.assertFalse(host_key.exists() or cloud.exists())
