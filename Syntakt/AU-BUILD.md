# Syntakt AUv2 for Logic Pro

This build uses XcodeGen to generate an Xcode project with a `Syntakt-AU`
aggregate target. That target calls CMake/Ninja and the existing pinned DPF AUv2
wrapper to produce `syntakt.component`. It is an AU instrument (`aumu`), with
subtype `sntk` and manufacturer `Simo`. The component contains both `x86_64` and
`arm64` code. This is not an AUv3 extension.

## Prerequisites

- An Intel or Apple Silicon Mac, with macOS 12 or newer.
- Xcode, selected with `xcode-select`, with its first-launch setup completed.
- Homebrew packages: `brew install xcodegen cmake ninja python`.
  XcodeGen 2.42.0 or newer is required.
- Internet access to GitHub during dependency bootstrap.

Either Mac architecture can compile both slices using Apple's SDK. Your Mac
can validate its native slice; an Intel Mac cannot execute the ARM slice.
Test on both architectures before distributing the component.

The generated Xcode project is ignored by Git; `project.yml` is its source.
The AU uses the existing engine and NanoVG/OpenGL interface. It does not require
JUCE, a separate VST SDK, or an Apple Developer account for local ad-hoc signing.

## Prepare dependencies and generate the project

From this repository's `Syntakt` directory:

```bash
bash source/vst/scripts/bootstrap-au-mac.sh
xcodegen generate --spec project.yml
open SyntaktAU.xcodeproj
```

Select the `Syntakt-AU` scheme and Build (Command-B). Release is the default;
Debug is also available. The aggregate target delegates compilation to CMake,
so compiler diagnostics come from its script phase, and Xcode Clean does not
delete the external CMake cache. This project is a build entry point, not a
native Xcode source-debugging target. Archiving it is not a distribution workflow.

Alternatively, build the generated project from the terminal:

```bash
xcodebuild -project SyntaktAU.xcodeproj -scheme Syntakt-AU -configuration Release build
```

The bootstrap pins DPF to `4238e1c7f0351bbe488d79f0899c540543ac7583`, applies
the existing offline-render patch, and invokes Syntakt's Unicorn builder. That
builder checks Unicorn's pinned revision and the patch SHA-256 values. The
bundled `source/dtcore` supplies the common engine. No private sibling checkout
is needed. Re-run bootstrap after changing dependency patches. Only use a
dedicated dependency cache: the existing Unicorn helper resets its cached sources.

The default cache is `~/Library/Caches/ElektronEmu/Syntakt-AU/universal`. To use
another path, pass it to bootstrap and to the build script, or set `ST_AU_WORK`
in the Xcode build settings / `xcodebuild` command. The dependency cache path
must not contain whitespace or colons: upstream Unicorn/QEMU rejects those
paths. The repository checkout can contain spaces. No network fetch runs
during the ordinary build.

Bootstrap builds Unicorn separately under `x86_64/` and `arm64/`. Each uses an
Apple Clang wrapper selecting that architecture for compiler probes and
compilation, and an explicit QEMU configuration CPU (including a pinned build
patch to bypass Darwin's native CPU detection). Ordinary AU builds use the same
wrappers and SDK zlib, avoiding a host-only Homebrew zlib. Both plug-in binaries
are checked with `lipo`, merged into one bundle, and signed after merging.
Bootstrap and compilation take longer because each architecture is built separately.

If updating from the earlier ARM-only workflow, pull the latest branch, rerun
bootstrap, and regenerate the Xcode project. The new `universal` cache keeps
earlier ARM-only dependencies separate; they are not deleted or reused.

## Install and validate

The built component is:

```text
~/Library/Caches/ElektronEmu/Syntakt-AU/universal/build/bin/syntakt.component
```

For a first local installation, close Logic and run from `Syntakt`:

```bash
INSTALL=1 bash source/vst/scripts/build-au-mac.sh
auval -v aumu sntk Simo
```

To inspect the architectures in the finished component:

```bash
lipo -archs ~/Library/Caches/ElektronEmu/Syntakt-AU/universal/build/bin/syntakt.component/Contents/MacOS/syntakt
```

Expect `x86_64 arm64` (order may differ). On your Intel Mac, `auval` and Logic
test the Intel slice. Validate the ARM slice separately on Apple Silicon.

The script installs into `~/Library/Audio/Plug-Ins/Components/`. It refuses to
replace an existing component; move your previous `syntakt.component` aside
before reinstalling. Check for another Syntakt AU in `/Library/Audio/Plug-Ins/Components/`
if Logic shows duplicate registrations. The VST3 can remain installed.

The script checks that the bundle contains no firmware/state filenames, ad-hoc
signs it, and verifies the signature. The filename check does not prove absence
of embedded firmware bytes when firmware reference files are unavailable.
No firmware is downloaded, copied, or embedded by this build.
The optional `DT_PANEL_IMAGE` environment variable selects a local panel PNG;
otherwise the bundled photo is used when present, with a schematic fallback.

Provide your own **Syntakt OS 1.41** firmware at:

```text
~/Library/Application Support/Elektron Emu/Syntakt/Firmware/Syntakt_OS1.41.syx
```

Then open Logic's Plug-in Manager, rescan Syntakt, and create a software
instrument track. Check MIDI notes, transport/tempo sync, output-channel routing,
automation, UI opening/resizing, first boot, project save/reopen, and both
real-time and offline bounce. The engine exposes six output channels; confirm
how this DPF AU wrapper presents them in Logic rather than assuming three
independently selectable stereo buses. Existing Syntakt limits still apply:
analog tracks 9–12 are absent and the README documents one active instance.

## Validation boundaries

The Linux cloud environment can check the scripts, exercise build orchestration
with mocked Apple tools, and compile Syntakt's portable C core. It cannot run
XcodeGen's macOS executable, Apple SDK compilation, code signing, `auval`, or
Logic. The macOS workflow must be built and validated locally before treating
this component as working. Distribution signing/notarization and AUv3 packaging
are separate work.

Run the portable build-script tests from the repository root with:

```bash
python3 -m unittest discover -s Syntakt/tests -v
```
