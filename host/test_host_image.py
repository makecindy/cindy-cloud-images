from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import json
import unittest

spec = importlib.util.spec_from_file_location(
    "host_image", Path(__file__).with_name("prepare-host-image.py")
)
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class HostImageTest(unittest.TestCase):
    def test_verified_release_is_inert_and_repeatable(self):
        with TemporaryDirectory() as work:
            root, release = (
                Path(work).resolve() / "root",
                Path(work).resolve() / "artifact",
            )
            (release / "bin").mkdir(parents=True)
            (release / "release.json").write_text(
                json.dumps(dict(region="cn", platform="linux", arch="x64"))
            )
            for name in ("cindy-host", "bin/node", "bin/host.mjs"):
                (release / name).write_text("exit 37")
                (release / name).chmod(0o755)
            files = {
                str(p.relative_to(release)): image.digest(p)
                for p in release.rglob("*")
                if p.is_file()
            }
            manifest = release / "SHA256SUMS.json"
            manifest.write_text(json.dumps(files))
            pin = image.digest(manifest)
            with self.assertRaises(ValueError):
                image.install(release, root, pin, "global", "x64")
            for _ in range(2):
                image.install(release, root, pin, "cn", "x64")
            self.assertIn(
                pin, (root / "etc/systemd/user/cindy-cloud-host.service").read_text()
            )
            self.assertFalse((root / "home").exists())
            self.assertFalse((root / "etc/systemd/user/default.target.wants").exists())
            (root / "opt/cindy-cloud-host" / pin / "extra").touch()
            with self.assertRaises(ValueError):
                image.install(release, root, pin, "cn", "x64")
            (release / "bin/node").write_text("modified")
            with self.assertRaises(ValueError):
                image.install(release, root, pin, "cn", "x64")
