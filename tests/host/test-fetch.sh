#!/bin/sh
# Host-side tests for the build's download checks: build/fetch.sh and the Rust manifest
# check in build/install-tool.sh. A stub curl first on PATH writes known bytes to the -o
# file, so no network is used. The expected checksums below are fixed values for those
# bytes, computed independently of fetch.sh.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
F="$(cd "$(dirname "$0")/../.." && pwd)/build/fetch.sh"
I="$(cd "$(dirname "$0")/../.." && pwd)/build/install-tool.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT INT TERM
mkdir "$T/bin"
# The stub logs each call, writes BODY to the file after -o, and fails with curl's
# HTTP error code 22 when STUB_FAIL is set, leaving a partial file behind.
cat >"$T/bin/curl" <<'EOF'
#!/bin/sh
echo called >>"$STUB_LOG"
out=
while [ $# -gt 0 ]; do
	case "$1" in
	-o)
		out=$2
		shift
		;;
	esac
	shift
done
printf 'agentainer fetch test\n' >"$out"
[ -z "${STUB_FAIL:-}" ] || exit 22
EOF
chmod +x "$T/bin/curl"
export STUB_LOG="$T/curl.log"
URL=https://example.com/file.tar.gz
SHA256=fee36b0b1abe5cdd29ac87c36374184a940b406e8488b9907f9be47632232db0
SHA512=33b1e9689cf15b932c2b2d31df58878ae18a0974ed0b57bd44f28d54fce22ef62b6c02e9844ddc9547aa7925b5bee9d4a83085109e21d18efe12f552344cfde6
SRI=sha512-M7HpaJzxW5MsKy0x31iHiuGKCXTtC1e9RPKNVPziLvYrbALphE3clUeqeSW1vunUqDCFEJ4h0Y7+EvVSNEz95g==
# Same length and form as the good values, last character changed.
BAD256=fee36b0b1abe5cdd29ac87c36374184a940b406e8488b9907f9be47632232db1
BAD512=33b1e9689cf15b932c2b2d31df58878ae18a0974ed0b57bd44f28d54fce22ef62b6c02e9844ddc9547aa7925b5bee9d4a83085109e21d18efe12f552344cfde7
BADSRI=sha512-M7HpaJzxW5MsKy0x31iHiuGKCXTtC1e9RPKNVPziLvYrbALphE3clUeqeSW1vunUqDCFEJ4h0Y7+EvVSNEz95A==

# fetch ALGO EXPECTED: runs fetch.sh into a fresh $T/out and prints "rc=N" and its stderr.
fetch() {
	rm -f "$T/out" "$STUB_LOG"
	err=$(PATH="$T/bin:$PATH" sh "$F" "$URL" "$1" "$2" "$T/out" 2>&1 >/dev/null)
	printf 'rc=%s\n%s\n' "$?" "$err"
}
log_state() {
	if [ -e "$STUB_LOG" ]; then echo present; else echo absent; fi
}
file_state() {
	if [ -e "$T/out" ]; then echo present; else echo absent; fi
}

# accepts NAME ALGO EXPECTED
accepts() {
	out=$(fetch "$2" "$3")
	assert_eq "$1: downloads once" called "$(cat "$STUB_LOG" 2>/dev/null)"
	assert_contains "$1: exits 0" "rc=0" "$out"
	assert_eq "$1: keeps the file" "agentainer fetch test" "$(cat "$T/out" 2>/dev/null)"
}
# rejects NAME ALGO EXPECTED MESSAGE
rejects() {
	out=$(fetch "$2" "$3")
	case "$out" in
	rc=0*) fail "$1: exits non-zero" "$out" ;;
	rc=*) pass "$1: exits non-zero" ;;
	*) fail "$1: exits non-zero" "fetch did not run: $out" ;;
	esac
	assert_contains "$1: says why" "$4" "$out"
	assert_eq "$1: deletes the file" absent "$(file_state)"
}

accepts "sha256 match" sha256 "$SHA256"
rejects "sha256 mismatch" sha256 "$BAD256" "checksum mismatch"
rejects "sha256 given an uppercase hash" sha256 "$(printf %s "$SHA256" | tr a-f A-F)" "checksum mismatch"
rejects "sha256 given the sha512" sha256 "$SHA512" "checksum mismatch"

accepts "sha512 match" sha512 "$SHA512"
rejects "sha512 mismatch" sha512 "$BAD512" "checksum mismatch"
rejects "sha512 given the sri form" sha512 "$SRI" "checksum mismatch"

accepts "sri match" sri "$SRI"
rejects "sri mismatch" sri "$BADSRI" "checksum mismatch"
rejects "sri without the sha512- prefix" sri "${SRI#sha512-}" "checksum mismatch"
rejects "sri given the hex sha512" sri "$SHA512" "checksum mismatch"

rejects "empty expected checksum" sha256 "" "no expected checksum"
assert_eq "empty expected checksum: nothing is downloaded" absent "$(log_state)"

rejects "unknown algorithm" md5 "$SHA256" "unknown algorithm"
out=$(fetch md5 "$SHA256")
assert_contains "unknown algorithm: exits 2" "rc=2" "$out"
assert_eq "unknown algorithm: nothing is downloaded" absent "$(log_state)"

out=$(
	export STUB_FAIL=1
	fetch sha256 "$SHA256"
)
assert_contains "download failure: exits 1" "rc=1" "$out"
assert_contains "download failure: says why" "download failed" "$out"
assert_eq "download failure: deletes the partial file" absent "$(file_state)"

# check-rust-manifest: rustup's re-serialized copy of the channel manifest must carry the
# same urls and hashes as the pinned file, and its update hash must be the pin's prefix.
R="$T/rust"
mkdir "$R"
PIN=ce6dddc886364f8d786514771212cebe9b731ba82d6b859951c6b0ccc516b6a2
cat >"$R/pinned.toml" <<'EOF'
manifest-version = "2"
date = "2026-10-01"
[pkg.rustc]
version = "1.99.0"
[pkg.rustc.target.x86_64-unknown-linux-gnu]
available = true
url = "https://static.rust-lang.org/dist/2026-10-01/rustc-1.99.0-x86_64-unknown-linux-gnu.tar.gz"
hash = "1111111111111111111111111111111111111111111111111111111111111111"
xz_url = "https://static.rust-lang.org/dist/2026-10-01/rustc-1.99.0-x86_64-unknown-linux-gnu.tar.xz"
xz_hash = "2222222222222222222222222222222222222222222222222222222222222222"
[pkg.rustc.target."thumbv8m.base-none-eabi"]
available = false
[[artifacts.source-code.target."*"]]
url = "https://static.rust-lang.org/dist/2026-10-01/rustc-1.99.0-src.tar.gz"
hash-sha256 = "3333333333333333333333333333333333333333333333333333333333333333"
EOF
# rustup's copy leaves out the artifacts tables.
sed '/artifacts/,$d' "$R/pinned.toml" >"$R/used.toml"
printf %s ce6dddc886364f8d7865 >"$R/update-hash"
# rust_check USED UPDATE_HASH: runs the check and prints "rc=N" and its stderr.
rust_check() {
	err=$(TARGETARCH=amd64 bash "$I" check-rust-manifest "$R/pinned.toml" "$PIN" "$1" "$2" 2>&1 >/dev/null)
	printf 'rc=%s\n%s\n' "$?" "$err"
}
assert_eq "rust: the pinned manifest passes" "rc=0" "$(rust_check "$R/used.toml" "$R/update-hash")"
sed 's/^xz_hash = "2/xz_hash = "4/' "$R/used.toml" >"$R/changed-hash.toml"
out=$(rust_check "$R/changed-hash.toml" "$R/update-hash")
assert_contains "rust: a changed component hash fails" "rc=1" "$out"
assert_contains "rust: names the changed key" "x86_64-unknown-linux-gnu] xz_hash differs" "$out"
sed 's/1.99.0-x86_64-unknown-linux-gnu.tar.gz/1.99.0-evil.tar.gz/' "$R/used.toml" >"$R/changed-url.toml"
assert_contains "rust: a changed url fails" "rc=1" "$(rust_check "$R/changed-url.toml" "$R/update-hash")"
printf '[pkg.rustc.target.aarch64-unknown-linux-gnu]\nhash = "%s"\n' "$PIN" >>"$R/extra.toml"
cat "$R/used.toml" "$R/extra.toml" >"$R/extra-target.toml"
assert_contains "rust: a target the pin lacks fails" "rc=1" "$(rust_check "$R/extra-target.toml" "$R/update-hash")"
grep -v hash "$R/used.toml" >"$R/no-hash.toml"
out=$(rust_check "$R/no-hash.toml" "$R/update-hash")
assert_contains "rust: a copy with no hashes fails" "rc=1" "$out"
assert_contains "rust: says there are no hashes" "no component hashes" "$out"
printf %s ce6dddc886364f8d7866 >"$R/other-hash"
out=$(rust_check "$R/used.toml" "$R/other-hash")
assert_contains "rust: another manifest's update hash fails" "rc=1" "$out"
assert_contains "rust: says the manifest differs" "rustup used a manifest" "$out"
printf %s "$PIN" >"$R/full-hash"
assert_contains "rust: a full hash in the update file fails" "rc=1" "$(rust_check "$R/used.toml" "$R/full-hash")"
assert_contains "rust: a missing update hash fails" "rc=1" "$(rust_check "$R/used.toml" "$R/nonexistent")"
assert_contains "rust: a missing copy fails" "rc=1" "$(rust_check "$R/nonexistent" "$R/update-hash")"

# Completion order may differ while the set of installed Rust components stays the same.
mkdir -p "$R/first" "$R/second"
printf '%s\n' rustc cargo clippy rustfmt >"$R/first/components"
printf '%s\n' clippy rustfmt cargo rustc >"$R/second/components"
printf '%s\n' cargo clippy rustc rustfmt >"$R/expected-components"
chmod 640 "$R/first/components"
normalize_components() {
	err=$(TARGETARCH=amd64 bash "$I" normalize-rust-components "$1" 2>&1 >/dev/null)
	printf 'rc=%s\n%s' "$?" "$err"
}
assert_eq "rust: normalizes first component order" "rc=0" "$(normalize_components "$R/first/components")"
assert_eq "rust: normalizes second component order" "rc=0" "$(normalize_components "$R/second/components")"
assert_eq "rust: component order is canonical" "$(cat "$R/expected-components")" "$(cat "$R/first/components")"
assert_eq "rust: completion order does not change component bytes" "$(cat "$R/first/components")" "$(cat "$R/second/components")"
assert_eq "rust: normalization keeps file permissions" "0o640" "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$R/first/components")"
assert_eq "rust: normalization is idempotent" "rc=0" "$(normalize_components "$R/first/components")"
assert_eq "rust: normalization keeps every component" "$(cat "$R/expected-components")" "$(cat "$R/first/components")"
assert_contains "rust: a missing components file fails" "rc=1" "$(normalize_components "$R/no-components")"

# extract-zip: the AWS CLI installer zip needs its Unix permission bits restored.
Z="$T/zip"
mkdir -p "$Z"
python3 - "$Z" <<'EOF'
import stat
import sys
import zipfile


def entry(z, name, mode, data=b""):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    z.writestr(info, data)


with zipfile.ZipFile(sys.argv[1] + "/good.zip", "w") as z:
    entry(z, "aws/", stat.S_IFDIR | 0o755)
    entry(z, "aws/install", stat.S_IFREG | 0o755, b"#!/bin/sh\n")
    entry(z, "aws/README.md", stat.S_IFREG | 0o644, b"readme\n")
    entry(z, "aws/open", stat.S_IFREG | 0o4777, b"x\n")
with zipfile.ZipFile(sys.argv[1] + "/link.zip", "w") as z:
    entry(z, "aws/", stat.S_IFDIR | 0o755)
    entry(z, "aws/link", stat.S_IFLNK | 0o777, b"/etc/passwd")
with zipfile.ZipFile(sys.argv[1] + "/up.zip", "w") as z:
    entry(z, "aws/", stat.S_IFDIR | 0o755)
    entry(z, "../escape", stat.S_IFREG | 0o644, b"x\n")
with zipfile.ZipFile(sys.argv[1] + "/abs.zip", "w") as z:
    entry(z, "aws/", stat.S_IFDIR | 0o755)
    entry(z, "/abs", stat.S_IFREG | 0o644, b"x\n")
with zipfile.ZipFile(sys.argv[1] + "/ro.zip", "w") as z:
    entry(z, "aws/", stat.S_IFDIR | 0o555)
    entry(z, "aws/dist/", stat.S_IFDIR | 0o555)
    entry(z, "aws/dist/aws", stat.S_IFREG | 0o755, b"#!/bin/sh\n")
EOF
extract() {
	mkdir -p "$2"
	err=$(TARGETARCH=amd64 bash "$I" extract-zip "$1" "$2" 2>&1 >/dev/null)
	printf 'rc=%s\n%s' "$?" "$err"
}
mode() { python3 -c 'import os,sys; print(oct(os.lstat(sys.argv[1]).st_mode & 0o7777))' "$1"; }
assert_eq "zip: extracts a good archive" "rc=0" "$(extract "$Z/good.zip" "$Z/good")"
assert_eq "zip: keeps the execute bit" "0o755" "$(mode "$Z/good/aws/install")"
assert_eq "zip: keeps a read-only file read-only" "0o644" "$(mode "$Z/good/aws/README.md")"
assert_eq "zip: drops setuid and other write" "0o755" "$(mode "$Z/good/aws/open")"
assert_contains "zip: a symlink entry fails" "rc=1" "$(extract "$Z/link.zip" "$Z/link")"
assert_eq "zip: no symlink is written" "none" "$(ls "$Z/link/aws/link" 2>/dev/null || echo none)"
# The targets sit two levels down, so "../escape" from the target would land in $Z/t.
mkdir -p "$Z/t"
assert_contains "zip: a ../ entry fails" "rc=1" "$(extract "$Z/up.zip" "$Z/t/up")"
assert_contains "zip: an absolute entry fails" "rc=1" "$(extract "$Z/abs.zip" "$Z/t/abs")"
# find prints END only when it exits 0, so a missing directory fails instead of passing.
assert_eq "zip: nothing is written outside or inside the targets" "END" \
	"$(find "$Z/t" -mindepth 1 ! -path "$Z/t/up" ! -path "$Z/t/abs" -print 2>&1 && echo END)"
assert_eq "zip: no absolute path is written" "none" "$(ls /abs 2>/dev/null || echo none)"
assert_eq "zip: read-only directories still receive their files" "rc=0" "$(extract "$Z/ro.zip" "$Z/ro")"
assert_eq "zip: the file under read-only directories is extracted" "0o755" "$(mode "$Z/ro/aws/dist/aws")"
assert_eq "zip: directory modes apply after extraction" "0o555 0o555" "$(mode "$Z/ro/aws") $(mode "$Z/ro/aws/dist")"
chmod -R u+w "$Z/ro"

finish
