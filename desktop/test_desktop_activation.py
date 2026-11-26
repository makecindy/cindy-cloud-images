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
        self.work = work
        self.home = work / "home"
        self.home.mkdir()
        self.defaults_dir = work / "etc/cindy-cloud-desktop"
        self.locale_file = work / "etc/default/locale"
        self.locale_file.parent.mkdir(parents=True)
        self.build_info = work / "linux-build-info"
        installer = Path(__file__).with_name("install-desktop.sh").read_text()
        self.installer = installer
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
        ).replace(
            "defaults_dir=/etc/cindy-cloud-desktop",
            'defaults_dir="$TEST_DEFAULTS_DIR"',
        ).replace(
            "locale_file=/etc/default/locale",
            'locale_file="$TEST_LOCALE_FILE"',
        ).replace("~ubuntu", '"$TEST_HOME"')

    def activate_desktop(self, *args, check=True):
        return subprocess.run(
            ["bash", "-c", self.activate, "activate", *args],
            check=check,
            env=dict(
                os.environ,
                TEST_HOME=str(self.home),
                TEST_BUILD_INFO=str(self.build_info),
                TEST_DEFAULTS_DIR=str(self.defaults_dir),
                TEST_LOCALE_FILE=str(self.locale_file),
            ),
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

    def test_activation_writes_os_locale_and_session_defaults_for_all_supported_languages(self):
        expected = {
            "en-US": ("en_US.UTF-8", "en_US:en"),
            "zh-CN": ("zh_CN.UTF-8", "zh_CN:zh"),
            "zh-TW": ("zh_TW.UTF-8", "zh_TW:zh"),
            "ja-JP": ("ja_JP.UTF-8", "ja_JP:ja"),
            "ko-KR": ("ko_KR.UTF-8", "ko_KR:ko"),
            "de-DE": ("de_DE.UTF-8", "de_DE:de"),
            "fr-FR": ("fr_FR.UTF-8", "fr_FR:fr"),
            "es-ES": ("es_ES.UTF-8", "es_ES:es"),
            "pt-BR": ("pt_BR.UTF-8", "pt_BR:pt"),
            "pt-PT": ("pt_PT.UTF-8", "pt_PT:pt"),
        }
        defaults_path = self.defaults_dir / "defaults"
        for tag, (lang, language) in expected.items():
            with self.subTest(language=tag):
                if defaults_path.exists():
                    defaults_path.unlink()
                if self.locale_file.exists():
                    self.locale_file.unlink()
                self.activate_desktop(tag, "1920x1080", "UTC")
                self.assertEqual(
                    defaults_path.read_text(),
                    f"LANG={lang}\nLANGUAGE={language}\nCINDY_DISPLAY=1920x1080\nTZ=UTC\n",
                )
                self.assertEqual(
                    self.locale_file.read_text(),
                    f"LANG={lang}\nLANGUAGE={language}\n",
                )
                # Retrying activation with the same arguments preserves user edits to /etc/default/locale.
                self.locale_file.write_text("LANG=en_US.UTF-8\n")
                self.activate_desktop(tag, "1920x1080", "UTC")
                self.assertEqual(self.locale_file.read_text(), "LANG=en_US.UTF-8\n")
                # Conflicting activation arguments fail closed.
                conflict = self.activate_desktop(tag, "1600x1000", "UTC", check=False)
                self.assertEqual(conflict.returncode, 1)

        invalid = self.activate_desktop("xx-YY", "1920x1080", "UTC", check=False)
        self.assertEqual(invalid.returncode, 2)

        for lang, _ in expected.values():
            self.assertIn(lang, self.installer)
        for pkg in (
            "language-pack-en",
            "language-pack-gnome-en",
            "language-pack-zh-hans",
            "language-pack-gnome-zh-hans",
            "language-pack-zh-hant",
            "language-pack-gnome-zh-hant",
            "language-pack-ja",
            "language-pack-gnome-ja",
            "language-pack-ko",
            "language-pack-gnome-ko",
            "language-pack-de",
            "language-pack-gnome-de",
            "language-pack-fr",
            "language-pack-gnome-fr",
            "language-pack-es",
            "language-pack-gnome-es",
            "language-pack-pt",
            "language-pack-gnome-pt",
        ):
            self.assertIn(pkg, self.installer)
        self.assertIn("GTK_A11Y LANG LANGUAGE TZ", self.installer)
