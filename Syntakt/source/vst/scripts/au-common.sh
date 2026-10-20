#!/usr/bin/env bash
# Shared by the AU scripts. Source this file; do not execute it directly.
set -euo pipefail

au_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# Xcode GUI builds do not inherit a terminal's Homebrew PATH.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
au_dpf_commit=4238e1c7f0351bbe488d79f0899c540543ac7583

au_require_mac() {
  if [[ $(uname -s) != Darwin ]]; then
    echo "error: AU builds require macOS and the Apple SDK." >&2
    exit 1
  fi
  case $(uname -m) in
    arm64|x86_64) ;;
    *)
      echo "error: AU builds require an Intel or Apple Silicon Mac." >&2
      exit 1
      ;;
  esac
  for tool in git cmake ninja python3 xcrun codesign lipo ditto; do
    command -v "$tool" >/dev/null || { echo "error: missing $tool" >&2; exit 1; }
  done
  au_sdk=$(xcrun --sdk macosx --show-sdk-path)
}

au_prepare_compilers() {
  local arch=$1 tool
  au_toolchain=$au_work/toolchains/$arch
  mkdir -p "$au_toolchain"
  for tool in clang clang++; do
    cat > "$au_toolchain/$tool" <<EOF
#!/bin/bash
exec /usr/bin/xcrun --sdk macosx $tool -arch $arch "\$@"
EOF
    chmod +x "$au_toolchain/$tool"
  done
}

au_set_work() {
  mkdir -p "$1"
  au_work=$(cd "$1" && pwd)
  # QEMU configure and DPF's emulator command parser require a simple cache path.
  if [[ $au_work == *[[:space:]:]* ]]; then
    echo "error: the AU dependency cache path must not contain whitespace or colons." >&2
    exit 1
  fi
}

au_check_dpf() {
  [[ $(git -C "$au_work/dpf" rev-parse HEAD) == "$au_dpf_commit" ]] || {
    echo "error: unexpected DPF revision; use a fresh dedicated AU work directory." >&2
    exit 1
  }
  git -C "$au_work/dpf" apply --reverse --check "$au_root/vst/patches/dpf-offline.patch" || {
    echo "error: DPF offline-render patch is missing; rerun bootstrap-au-mac.sh." >&2
    exit 1
  }
}
