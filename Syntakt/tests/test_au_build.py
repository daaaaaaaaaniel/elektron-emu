"""Portable orchestration checks; these do not compile or validate an Apple AU."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "source/vst/scripts"
class AUBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="syntakt au ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / "dependency cache"
        self.home = self.base / "user home"
        self.bin = self.base / "tools"
        self.bin.mkdir()
        self.log = self.base / "calls.jsonl"
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f"{self.bin}:{os.environ['PATH']}",
                        AU_TEST_LOG=str(self.log), CONFIGURATION="Debug")
        self.env.pop("INSTALL", None)
        self.env.pop("DTCORE_COMMIT", None)
        self.env.pop("DT_PANEL_IMAGE", None)
        tool = self.bin / "tool"
        tool.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['AU_TEST_LOG'], 'a') as f:
    f.write(json.dumps([name, *args]) + '\\n')
if name == 'uname':
    print(os.environ.get('AU_TEST_OS', 'Darwin') if args == ['-s'] else 'arm64')
elif name == 'git' and 'rev-parse' in args:
    print('4238e1c7f0351bbe488d79f0899c540543ac7583')
elif name == 'cmake' and '--build' in args:
    bundle = pathlib.Path(args[1]) / 'bin/syntakt.component/Contents'
    (bundle / 'MacOS').mkdir(parents=True, exist_ok=True)
    (bundle / 'MacOS/syntakt').write_text('mock Mach-O')
    (bundle / 'Info.plist').write_text('mock plist')
""")
        tool.chmod(0o755)
        for name in ("uname", "git", "cmake", "ninja", "xcrun", "codesign"):
            (self.bin / name).symlink_to(tool)

    def prepare_cache(self):
        (self.work / "dpf/.git").mkdir(parents=True)
        (self.work / "unicorn/lib").mkdir(parents=True)
        (self.work / "unicorn/lib/libunicorn.a").touch()
        (self.work / "unicorn/DTCORE-UNICORN.txt").touch()

    def run_build(self):
        return subprocess.run(["bash", str(SCRIPTS / "build-au-mac.sh"), str(self.work)],
                              env=self.env, text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_build_preserves_paths_and_selects_au(self):
        self.prepare_cache()
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        configure = next(c for c in calls if c[:2] == ["cmake", "-S"])
        self.assertIn("-DSYNTAKT_PLUGIN_FORMATS=au", configure)
        self.assertIn("-DCMAKE_BUILD_TYPE=Debug", configure)
        self.assertIn("-DCMAKE_OSX_ARCHITECTURES=arm64", configure)
        self.assertIn(f"-DDPF_ROOT={self.work}/dpf", configure)
        self.assertIn(["cmake", "--build", str(self.work / "build"),
                       "--target", "syntakt-au"], calls)
        self.assertTrue(any(c[:3] == ["codesign", "--verify", "--strict"] for c in calls))
        self.assertFalse(any("clone" in c or "fetch" in c for c in calls))

    def test_missing_bootstrap_stops_before_configure(self):
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bootstrap-au-mac.sh", result.stderr)
        self.assertFalse(any(c[0] == "cmake" for c in self.calls()))

    def test_linux_is_rejected(self):
        self.env["AU_TEST_OS"] = "Linux"
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require macOS", result.stderr)

    def test_install_preserves_existing_component(self):
        self.prepare_cache()
        self.env["INSTALL"] = "1"
        destination = self.home / "Library/Audio/Plug-Ins/Components/syntakt.component"
        destination.mkdir(parents=True)
        sentinel = destination / "user-data"
        sentinel.write_text("preserve me")
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(sentinel.read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()
