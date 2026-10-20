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
        self.temp = tempfile.TemporaryDirectory(prefix="syntakt-au-")
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
        for name in ("INSTALL", "DTCORE_COMMIT", "DT_PANEL_IMAGE", "AU_TEST_OS",
                     "AU_TEST_HOST", "AU_TEST_MISSING_ARCH", "AU_TEST_BAD_PLIST"):
            self.env.pop(name, None)
        tool = self.bin / "tool"
        tool.write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['AU_TEST_LOG'], 'a') as f:
    f.write(json.dumps([name, *args]) + '\\n')
if name == 'uname':
    print(os.environ.get('AU_TEST_OS', 'Darwin') if args == ['-s']
          else os.environ.get('AU_TEST_HOST', 'arm64'))
elif name == 'xcrun':
    print('/mock/MacOSX.sdk')
elif name == 'git' and 'rev-parse' in args:
    print('4238e1c7f0351bbe488d79f0899c540543ac7583')
elif name == 'bash':
    if args[0].endswith('/core/scripts/build-unicorn.sh'):
        prefix = pathlib.Path(args[1])
        (prefix / 'lib').mkdir(parents=True, exist_ok=True)
        (prefix / 'lib/libunicorn.a').touch()
        (prefix / 'DTCORE-UNICORN.txt').touch()
        keys = ['ARCHFLAGS', 'CMAKE_OSX_ARCHITECTURES', 'CMAKE_OSX_SYSROOT',
                'CMAKE_C_COMPILER', 'CMAKE_CXX_COMPILER', 'UNICORN_QEMU_CPU']
        with open(os.environ['AU_TEST_LOG'], 'a') as f:
            f.write(json.dumps(['unicorn-env', {k: os.environ[k] for k in keys}]) + '\\n')
    else:
        os.execv('/bin/bash', ['/bin/bash', *args])
elif name == 'cmake' and '--build' in args:
    build = pathlib.Path(args[1])
    bundle = build / 'bin/syntakt.component/Contents'
    (bundle / 'MacOS').mkdir(parents=True, exist_ok=True)
    (bundle / 'MacOS/syntakt').write_text('mock Mach-O: ' + build.parent.name)
    plist = 'different' if os.environ.get('AU_TEST_BAD_PLIST') and build.parent.name == 'arm64' else 'mock plist'
    (bundle / 'Info.plist').write_text(plist)
elif name == 'ditto':
    shutil.copytree(args[0], args[1], dirs_exist_ok=True)
elif name == 'lipo':
    if '-verify_arch' in args and os.environ.get('AU_TEST_MISSING_ARCH') in args[1:-1]:
        sys.exit('mock missing architecture')
    if '-create' in args:
        pathlib.Path(args[args.index('-output') + 1]).write_text('mock universal Mach-O')
""")
        tool.chmod(0o755)
        for name in ("uname", "git", "cmake", "ninja", "xcrun", "codesign",
                     "lipo", "ditto", "bash"):
            (self.bin / name).symlink_to(tool)

    def prepare_cache(self):
        (self.work / "dpf/.git").mkdir(parents=True)
        for arch in ("x86_64", "arm64"):
            prefix = self.work / arch / "unicorn"
            (prefix / "lib").mkdir(parents=True)
            (prefix / "lib/libunicorn.a").touch()
            (prefix / "DTCORE-UNICORN.txt").touch()

    def run_script(self, name="build-au-mac.sh", work=None):
        return subprocess.run(["/bin/bash", str(SCRIPTS / name), str(work or self.work)],
                              env=self.env, text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_builds_both_slices_on_either_host_and_signs_after_merging(self):
        self.prepare_cache()
        for host in ("x86_64", "arm64"):
            with self.subTest(host=host):
                self.log.unlink(missing_ok=True)
                self.env["AU_TEST_HOST"] = host
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.calls()
                configure = [c for c in calls if c[:2] == ["cmake", "-S"]]
                self.assertEqual(len(configure), 2)
                for arch, call in zip(("x86_64", "arm64"), configure):
                    self.assertIn("-DSYNTAKT_PLUGIN_FORMATS=au", call)
                    self.assertIn("-DCMAKE_BUILD_TYPE=Debug", call)
                    self.assertIn(f"-DCMAKE_OSX_ARCHITECTURES={arch}", call)
                    self.assertIn(f"-DDPF_ROOT={self.work}/dpf", call)
                    self.assertIn(f"-DDTCORE_UNICORN_PREFIX={self.work}/{arch}/unicorn", call)
                    self.assertIn(f"-DCMAKE_C_COMPILER={self.work}/toolchains/{arch}/clang", call)
                    self.assertIn("-DZLIB_LIBRARY=/mock/MacOSX.sdk/usr/lib/libz.tbd", call)
                    self.assertIn(["cmake", "--build", str(self.work / arch / "build"),
                                   "--target", "syntakt-au"], calls)
                merged = self.work / "build/bin/syntakt.component/Contents/MacOS/syntakt"
                self.assertIn(["lipo", "-verify_arch", "x86_64", "arm64", str(merged)], calls)
                merge_index = next(i for i, c in enumerate(calls) if c[:2] == ["lipo", "-create"])
                sign_index = next(i for i, c in enumerate(calls) if c[0] == "codesign")
                self.assertLess(merge_index, sign_index)
                self.assertEqual(merged.read_text(), "mock universal Mach-O")
                self.assertTrue(any(c[:3] == ["codesign", "--verify", "--strict"] for c in calls))
                self.assertFalse(any("clone" in c or "fetch" in c for c in calls))

    def test_bootstrap_selects_compiler_and_qemu_cpu_for_each_slice(self):
        self.work = self.base / "cache"
        self.prepare_cache()
        self.env["AU_TEST_HOST"] = "x86_64"
        result = self.run_script("bootstrap-au-mac.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        delegates = [c for c in calls if c[0] == "unicorn-env"]
        self.assertEqual(len(delegates), 2)
        for arch, call in zip(("x86_64", "arm64"), delegates):
            settings = call[1]
            self.assertEqual(settings["ARCHFLAGS"], f"-arch {arch}")
            self.assertEqual(settings["CMAKE_OSX_ARCHITECTURES"], arch)
            self.assertEqual(settings["UNICORN_QEMU_CPU"], "aarch64" if arch == "arm64" else arch)
            self.assertEqual(settings["CMAKE_OSX_SYSROOT"], "/mock/MacOSX.sdk")
            compiler = Path(settings["CMAKE_C_COMPILER"])
            self.assertIn(f"clang -arch {arch}", compiler.read_text())
            self.assertTrue(os.access(compiler, os.X_OK))
            self.assertIn(["lipo", "-verify_arch", arch,
                           str(self.work / arch / "unicorn/lib/libunicorn.a")], calls)

    def test_bootstrap_rejects_qemu_incompatible_cache_paths(self):
        result = self.run_script("bootstrap-au-mac.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cache path must not contain", result.stderr)
        self.assertFalse(any(c[0] == "git" for c in self.calls()))

    def test_missing_bootstrap_stops_before_configure(self):
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bootstrap-au-mac.sh", result.stderr)
        self.assertFalse(any(c[0] == "cmake" for c in self.calls()))

    def test_missing_arm_dependency_stops_before_configure(self):
        self.prepare_cache()
        (self.work / "arm64/unicorn/lib/libunicorn.a").unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bootstrap-au-mac.sh", result.stderr)
        self.assertFalse(any(c[0] == "cmake" for c in self.calls()))

    def test_wrong_dependency_architecture_stops_before_configure(self):
        self.prepare_cache()
        self.env["AU_TEST_MISSING_ARCH"] = "arm64"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] == "cmake" for c in self.calls()))

    def test_different_metadata_prevents_merge_and_signing(self):
        self.prepare_cache()
        self.env["AU_TEST_BAD_PLIST"] = "1"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata differ", result.stderr)
        self.assertFalse(any(c[:2] == ["lipo", "-create"] or c[0] == "codesign" for c in self.calls()))

    def test_linux_is_rejected(self):
        self.env["AU_TEST_OS"] = "Linux"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require macOS", result.stderr)

    def test_install_preserves_existing_component(self):
        self.prepare_cache()
        self.env["INSTALL"] = "1"
        destination = self.home / "Library/Audio/Plug-Ins/Components/syntakt.component"
        destination.mkdir(parents=True)
        sentinel = destination / "user-data"
        sentinel.write_text("preserve me")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(sentinel.read_text(), "preserve me")

    def test_installs_universal_component(self):
        self.prepare_cache()
        self.env["INSTALL"] = "1"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.home / "Library/Audio/Plug-Ins/Components/syntakt.component/Contents/MacOS/syntakt"
        self.assertEqual(installed.read_text(), "mock universal Mach-O")


if __name__ == "__main__":
    unittest.main()
