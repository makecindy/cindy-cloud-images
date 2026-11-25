import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class DesktopFirstBootUpdateTest(unittest.TestCase):
    """Runs the generated first-boot update script against stubbed package and network tools."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.state = self.work / "state"
        self.build_info = self.work / "linux-build-info"
        self.calls = self.work / "calls"
        self.cdn = self.work / "cdn"
        self.deb = self.work / "new.deb"
        self.deb.write_bytes(b"cindy 0.1.147 package bytes")
        installer = Path(__file__).with_name("install-desktop.sh").read_text()
        _, start, rest = installer.partition("<<'UPDATE'\n")
        update, end, _ = rest.partition("\nUPDATE\n")
        self.assertTrue(start and end, "The installer must emit the first-boot update script")
        stubs = """
dpkg-query() {
    case $1 in
        -S) [[ $TEST_OWNED == yes ]] && printf '%s: %s\\n' "$TEST_PACKAGE" "$2" ;;
        -W) local format=${2#-f=}
            format=${format//'${Version}'/$TEST_INSTALLED}
            printf '%s' "${format//'${Status}'/$TEST_STATUS}" ;;
    esac
}
dpkg() {
    case $1 in
        --print-architecture) echo amd64 ;;
        --configure) printf 'dpkg %s\n' "$*" >> "$TEST_CALLS" ;;
        --compare-versions) [[ $(printf '%s\\n%s\\n' "$2" "$4" | sort -V | tail -1) == "$2" && "$2" != "$4" ]] ;;
    esac
}
dpkg-deb() {
    case $3 in
        Package) echo "$TEST_DEB_PACKAGE" ;;
        Architecture) echo amd64 ;;
        Version) echo "$TEST_DEB_VERSION" ;;
    esac
}
date() {
    local tick=0 times=($TEST_TIMES)
    [[ -f $TEST_CLOCK ]] && tick=$(<"$TEST_CLOCK")
    echo $(( tick + 1 )) > "$TEST_CLOCK"
    echo "${times[tick]:-${times[${#times[@]}-1]}}"
}
curl() {
    local out= url=
    while [[ $# -gt 0 ]]; do
        case $1 in
            -o) out=$2; shift 2 ;;
            --max-time) printf '%s\n' "$2" >> "$TEST_LIMITS"; shift 2 ;;
            --retry|--connect-timeout|--speed-limit|--speed-time|--proto|--proto-redir) shift 2 ;;
            -*) shift ;;
            *) url=$1; shift ;;
        esac
    done
    printf 'curl %s\\n' "$url" >> "$TEST_CALLS"
    local name=${url##*/}
    [[ -f "$TEST_CDN/$name" ]] || return 22
    cp "$TEST_CDN/$name" "$out"
}
apt-get() { printf 'apt-get %s\\n' "$*" >> "$TEST_CALLS"; [[ $TEST_INSTALL_OK == yes ]]; }
"""
        self.script = stubs + update.replace(
            "state=/var/lib/cindy-cloud-desktop", 'state="$TEST_STATE"'
        ).replace(
            "build_info=/usr/lib/cindy/resources/linux-build-info", 'build_info="$TEST_BUILD_INFO"'
        )

    def publish(self, version="0.1.147", digest=None, file="app/linux-x64/cindy-0.1.147-amd64.deb"):
        self.cdn.mkdir(exist_ok=True)
        manifest = {
            "app": {
                "version": version,
                "installer": {
                    "file": file,
                    "sha256": digest or hashlib.sha256(self.deb.read_bytes()).hexdigest(),
                    "size": self.deb.stat().st_size,
                },
            }
        }
        (self.cdn / "manifest-linux-x64.json").write_text(json.dumps(manifest))
        (self.cdn / file.rsplit("/", 1)[-1]).write_bytes(self.deb.read_bytes())

    def run_update(self, region="cn", installed="0.1.146", **overrides):
        self.build_info.write_text(f"cindy-linux-v1\n{installed}\nx64\n{region}\nCindy\n")
        env = dict(
            os.environ,
            TEST_STATE=str(self.state),
            TEST_BUILD_INFO=str(self.build_info),
            TEST_CALLS=str(self.calls),
            TEST_CDN=str(self.cdn),
            TEST_OWNED="yes",
            TEST_PACKAGE="cindy",
            TEST_INSTALLED=installed,
            TEST_DEB_PACKAGE="cindy",
            TEST_DEB_VERSION="0.1.147",
            TEST_INSTALL_OK="yes",
            TEST_STATUS="install ok installed",
            TEST_TIMES="1000",
            TEST_CLOCK=str(self.work / "clock"),
            TEST_LIMITS=str(self.work / "limits"),
        )
        env.update(overrides)
        result = subprocess.run(["bash", "-c", self.script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.state / "update.done").exists(), "The desktop waits for this marker")
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        self.calls.unlink(missing_ok=True)
        limits = Path(env["TEST_LIMITS"])
        self.limits = limits.read_text().split() if limits.exists() else []
        limits.unlink(missing_ok=True)
        Path(env["TEST_CLOCK"]).unlink(missing_ok=True)
        (self.state / "update.done").unlink()
        return calls, result.stdout

    def installs(self, calls):
        return [call for call in calls if call.startswith("apt-get ")]

    def test_installs_a_newer_release_from_the_baked_region(self):
        self.publish()
        for region, cdn in (
            ("cn", "https://hotfix.cindy.com.cn/cindy"),
            ("global", "https://hotfix.cindy.app/cindy"),
        ):
            with self.subTest(region=region):
                calls, output = self.run_update(region=region)
                self.assertEqual(calls[0], f"curl {cdn}/manifest-linux-x64.json")
                self.assertEqual(calls[1], f"curl {cdn}/app/linux-x64/cindy-0.1.147-amd64.deb")
                (install,) = self.installs(calls)
                self.assertIn("-o DPkg::Lock::Timeout=300 install -y --no-install-recommends", install)
                self.assertTrue(install.endswith("/cindy.deb"))
                self.assertIn("Installed Cindy 0.1.147, replacing 0.1.146", output)
                self.assertEqual(self.limits, ["60", "600"], "The download may use the whole install window")

    def test_keeps_a_current_release_without_downloading(self):
        self.publish(version="0.1.146")
        calls, output = self.run_update(installed="0.1.146")
        self.assertEqual(len(calls), 1)
        self.assertIn("Cindy 0.1.146 is current", output)
        calls, _ = self.run_update(installed="0.1.150")
        self.assertEqual(self.installs(calls), [])

    def test_keeps_the_baked_release_when_anything_does_not_match(self):
        self.publish()
        cases = {
            "digest": ({}, {"digest": "0" * 64}),
            "package": ({"TEST_DEB_PACKAGE": "cindydev"}, {}),
            "version": ({"TEST_DEB_VERSION": "0.1.145"}, {}),
            "foreign file": ({}, {"file": "app/linux-arm64/cindy-0.1.147-arm64.deb"}),
            "install": ({"TEST_INSTALL_OK": "no"}, {}),
        }
        for name, (env, manifest) in cases.items():
            with self.subTest(name):
                self.publish(**manifest)
                calls, _ = self.run_update(**env)
                if name == "install":
                    self.assertEqual(len(self.installs(calls)), 1)
                else:
                    self.assertEqual(self.installs(calls), [])

    def test_never_starts_replacing_the_package_late(self):
        self.publish()
        calls, output = self.run_update(TEST_TIMES="1000 1560")
        self.assertEqual(len(calls), 1, "Only the manifest is fetched")
        self.assertIn("No time left to download", output)
        calls, output = self.run_update(TEST_TIMES="1000 1000 1601")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.installs(calls), [])
        self.assertIn("Too late to install", output)
        calls, _ = self.run_update(TEST_TIMES="1000 1300")
        self.assertEqual(self.limits, ["60", "300"], "A late download only gets the rest of the window")
        self.assertEqual(len(self.installs(calls)), 1)

    def test_a_failed_install_does_not_leave_the_package_half_configured(self):
        self.publish()
        calls, output = self.run_update(TEST_INSTALL_OK="no")
        self.assertNotIn("dpkg --configure --pending", calls)
        self.assertIn("Install failed; Cindy is 0.1.146 (install ok installed)", output)
        calls, _ = self.run_update(TEST_INSTALL_OK="no", TEST_STATUS="install ok half-configured")
        self.assertEqual(calls[-1], "dpkg --configure --pending")

    def test_skips_without_a_manifest_package_or_region(self):
        calls, output = self.run_update()
        self.assertEqual(self.installs(calls), [])
        self.assertIn("Release manifest unavailable", output)
        self.publish()
        calls, _ = self.run_update(TEST_OWNED="no")
        self.assertEqual(calls, [])
        calls, _ = self.run_update(region="unknown")
        self.assertEqual(calls, [])
        calls, _ = self.run_update(TEST_PACKAGE="other")
        self.assertEqual(calls, [])


class DesktopInstallStartupTest(unittest.TestCase):
    def test_direct_install_queues_update_before_activation(self):
        installer = Path(__file__).with_name("install-desktop.sh").read_text()
        branch = 'if [[ $prepare_only = false ]]; then'
        _, marker, code = installer.rpartition(branch)
        self.assertTrue(marker, "The installer must have a direct-install branch")
        script = """
set -euo pipefail
systemctl() { echo "$*"; }
activate() { echo activate; }
""" + branch + code.replace("/usr/local/lib/cindy-cloud-desktop/activate", "activate")
        for prepare_only, expected in (
            ("false", ["start --no-block cindy-cloud-desktop-update.service", "activate"]),
            ("true", []),
        ):
            with self.subTest(prepare_only=prepare_only):
                result = subprocess.run(
                    ["bash", "-c", script],
                    env=dict(os.environ, prepare_only=prepare_only),
                    check=True, capture_output=True, text=True,
                )
                self.assertEqual(result.stdout.splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
