import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest


class DesktopActivationTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        self.home = work / "home"
        self.home.mkdir()
        self.build_info = work / "linux-build-info"
        installer = Path(__file__).with_name("install-desktop.sh").read_text()
        _, start, rest = installer.partition("<<'ACTIVATE'\n")
        activate, end, _ = rest.partition("\nACTIVATE\n")
        self.assertTrue(start and end, "The installer must emit the activation script")

        # Run the generated script without root or systemd. Redirect only the
        # machine-specific paths into the temporary guest fixture.
        self.activate = """
loginctl() { :; }
systemctl() { :; }
id() { printf '%s\\n' "$UID"; }
runuser() {
    [[ $1 == -u && $2 == ubuntu && $3 == -- ]] || return 1
    shift 3
    case $1 in
        bash) [[ ${!#} == "$TEST_HOME" ]] && "$@" ;;
        env) : ;; # systemctl --user
        *) return 1 ;;
    esac
}
""" + activate.replace(
            "build_info=/usr/lib/cindy/resources/linux-build-info",
            'build_info="$TEST_BUILD_INFO"',
        ).replace("~ubuntu", '"$TEST_HOME"')

    def activate_desktop(self):
        subprocess.run(
            ["bash", "-c", self.activate],
            check=True,
            env=dict(os.environ, TEST_HOME=str(self.home), TEST_BUILD_INFO=str(self.build_info)),
        )

    def test_defaults_follow_package_region_and_keep_user_choice(self):
        for region, directory in (("cn", "Cindy"), ("global", "CindyGlobal")):
            with self.subTest(region=region):
                self.build_info.write_text(f"cindy-linux-v1\n0.1.146\nx64\n{region}\nCindy\n")
                self.activate_desktop()
                config_dir = self.home / ".config" / directory
                settings = config_dir / "auto-update-settings.json"
                self.assertEqual(json.loads(settings.read_text()), {"autoRelaunchOnIdle": True})
                self.assertEqual(stat.S_IMODE(config_dir.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)

                disabled = '{"autoRelaunchOnIdle": false}\n'
                settings.write_text(disabled)
                self.activate_desktop()
                self.assertEqual(settings.read_text(), disabled)
                settings.unlink()
                config_dir.rmdir()

    def test_no_defaults_without_a_recognized_region(self):
        self.activate_desktop()
        self.build_info.write_text("cindy-linux-v1\n0.1.146\nx64\nunknown\nCindy\n")
        self.activate_desktop()
        self.assertFalse((self.home / ".config").exists())
