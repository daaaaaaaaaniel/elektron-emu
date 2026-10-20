"""Portable orchestration checks; these do not compile or validate an Apple AU."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "source/vst/scripts"


class AUBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="syntakt-au-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / "dependency-cache"
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
        exporter_source = self.base / "exporter-source"
        exporter_source.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
arch = pathlib.Path(__file__).parents[2].name
if arch != os.environ.get('AU_TEST_HOST', 'arm64'):
    sys.exit('cannot execute foreign metadata helper: ' + arch)
with open(os.environ['AU_TEST_LOG'], 'a') as f:
    f.write(json.dumps(['metadata-export', arch, os.getcwd(), *sys.argv[1:]]) + '\\n')
plist = 'different' if os.environ.get('AU_TEST_BAD_PLIST') and 'arm64' in pathlib.Path.cwd().parts else 'mock plist'
pathlib.Path('Info.plist').write_text(plist)
""")
        self.env["AU_TEST_EXPORT_SOURCE"] = str(exporter_source)
        tool = self.bin / "tool"
        tool.write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, subprocess, sys
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
elif name == 'cmake' and '-S' in args:
    build = pathlib.Path(args[args.index('-B') + 1])
    build.mkdir(parents=True, exist_ok=True)
    (build / 'mock-config.json').write_text(json.dumps(args))
elif name == 'cmake' and '--build' in args:
    build = pathlib.Path(args[1])
    bundle = build / 'bin/syntakt.component/Contents'
    (bundle / 'MacOS').mkdir(parents=True, exist_ok=True)
    (bundle / 'MacOS/syntakt').write_text('mock Mach-O: ' + build.parent.name)
    exporter = build / 'bin/syntakt-export'
    shutil.copyfile(os.environ['AU_TEST_EXPORT_SOURCE'], exporter)
    exporter.chmod(0o755)
    config = json.loads((build / 'mock-config.json').read_text())
    runner = next((c.split('=', 1)[1] for c in config
                   if c.startswith('-DCMAKE_CROSSCOMPILING_EMULATOR=')), '')
    command = ([runner] if runner else []) + [str(exporter), 'syntakt']
    subprocess.run(command, cwd=bundle, check=True)
elif name == 'ditto':
    shutil.copytree(args[0], args[1], dirs_exist_ok=True)
elif name == 'lipo':
    if '-verify_arch' in args:
        verify_index = args.index('-verify_arch')
        # Apple lipo treats every argument following -verify_arch as an arch.
        architectures = args[verify_index + 1:]
        if not architectures or any(a not in ('x86_64', 'arm64') for a in architectures):
            sys.exit('unknown architecture specification flag after -verify_arch')
        if verify_index != 1 or not pathlib.Path(args[0]).is_file():
            sys.exit('lipo verification requires an input file before -verify_arch')
        if os.environ.get('AU_TEST_MISSING_ARCH') in architectures:
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
                other = "arm64" if host == "x86_64" else "x86_64"
                for arch, call in zip((host, other), configure):
                    self.assertIn("-DSYNTAKT_PLUGIN_FORMATS=au", call)
                    self.assertIn("-DCMAKE_BUILD_TYPE=Debug", call)
                    self.assertIn(f"-DCMAKE_OSX_ARCHITECTURES={arch}", call)
                    self.assertIn(f"-DDPF_ROOT={self.work}/dpf", call)
                    self.assertIn(f"-DDTCORE_UNICORN_PREFIX={self.work}/{arch}/unicorn", call)
                    self.assertIn(f"-DCMAKE_C_COMPILER={self.work}/toolchains/{arch}/clang", call)
                    self.assertIn("-DZLIB_LIBRARY=/mock/MacOSX.sdk/usr/lib/libz.tbd", call)
                    runner = "" if arch == host else str(self.work / "native-au-export")
                    self.assertIn(f"-DCMAKE_CROSSCOMPILING_EMULATOR={runner}", call)
                    self.assertIn(["cmake", "--build", str(self.work / arch / "build"),
                                   "--target", "syntakt-au"], calls)
                exports = [c for c in calls if c[0] == "metadata-export"]
                self.assertEqual(len(exports), 2)
                self.assertEqual([c[1] for c in exports], [host, host])
                self.assertEqual([c[2] for c in exports], [
                    str(self.work / arch / "build/bin/syntakt.component/Contents")
                    for arch in (host, other)])
                self.assertEqual([c[3:] for c in exports], [["syntakt"], ["syntakt"]])
                merged = self.work / "build/bin/syntakt.component/Contents/MacOS/syntakt"
                self.assertIn(["lipo", str(merged), "-verify_arch", "x86_64", "arm64"], calls)
                merge_index = next(i for i, c in enumerate(calls) if c[:2] == ["lipo", "-create"])
                sign_index = next(i for i, c in enumerate(calls) if c[0] == "codesign")
                self.assertLess(merge_index, sign_index)
                self.assertEqual(merged.read_text(), "mock universal Mach-O")
                self.assertTrue(any(c[:3] == ["codesign", "--verify", "--strict"] for c in calls))
                self.assertFalse(any("clone" in c or "fetch" in c for c in calls))

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"),
                         "CMake and Ninja are required for the real command-execution check")
    def test_real_cmake_dpf_post_build_uses_native_exporter(self):
        self.prepare_cache()
        self.env["AU_TEST_HOST"] = "x86_64"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        source = self.base / "cmake fixture"
        source.mkdir()
        contents = self.base / "fixture-output"
        contents.mkdir()
        # Exercise the actual POST_BUILD recipe from the pinned DPF's
        # cmake/DPF-plugin.cmake, without requiring Apple compilers/frameworks.
        (source / "CMakeLists.txt").write_text('''
cmake_minimum_required(VERSION 3.20)
project(AUMetadataCheck NONE)
add_executable(syntakt-export IMPORTED)
set_target_properties(syntakt-export PROPERTIES IMPORTED_LOCATION "${FOREIGN_EXPORTER}")
add_custom_target(syntakt-au)
separate_arguments(CMAKE_CROSSCOMPILING_EMULATOR)
add_custom_command(TARGET syntakt-au POST_BUILD
  COMMAND ${CMAKE_CROSSCOMPILING_EMULATOR} "$<TARGET_FILE:syntakt-export>" "syntakt"
  WORKING_DIRECTORY "${CONTENTS}")
''')
        cmake = shutil.which("cmake")
        real_env = dict(self.env, PATH=os.environ["PATH"])
        build = self.base / "cmake-build"
        foreign = self.work / "arm64/build/bin/syntakt-export"

        def configure(runner):
            return subprocess.run([
                cmake, "-S", str(source), "-B", str(build), "-G", "Ninja",
                f"-DFOREIGN_EXPORTER={foreign}", f"-DCONTENTS={contents}",
                f"-DCMAKE_CROSSCOMPILING_EMULATOR={runner}"],
                env=real_env, text=True, capture_output=True)

        def build_metadata():
            return subprocess.run([cmake, "--build", str(build), "--target", "syntakt-au"],
                                  env=real_env, text=True, capture_output=True)

        result = configure("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = build_metadata()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot execute foreign metadata helper", result.stdout + result.stderr)
        self.assertFalse((contents / "Info.plist").exists())

        result = configure(str(self.work / "native-au-export"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = build_metadata()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((contents / "Info.plist").read_text(), "mock plist")
        self.assertIn(["metadata-export", "x86_64", str(contents), "syntakt"], self.calls())

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
            self.assertIn(["lipo", str(self.work / arch / "unicorn/lib/libunicorn.a"),
                           "-verify_arch", arch], calls)

    def test_bootstrap_rejects_qemu_incompatible_cache_paths(self):
        result = self.run_script("bootstrap-au-mac.sh", self.base / "cache with spaces")
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
