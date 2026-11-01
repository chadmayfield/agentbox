#!/bin/sh
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# Installs each extra in the image's catalog from the public npm registry with
# agentainer-extras, which runs the entry's check, then runs each installed bin from PATH.
# Needs network access to registry.npmjs.org, so CI does not run it. Run it by hand on each
# architecture after a catalog change:
#   IMAGE=localhost/agentainer:dev sh tests/host/test-extras-live.sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
c="agentainer-test-extras-live-$$"
trap '"$RUNTIME" rm -f "$c" >/dev/null 2>&1' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
catalog=/usr/local/share/agentainer/extras
ext=/var/lib/agentainer/active/npm/extras
if ! run_bg "$c" || ! wait_for 30 "$RUNTIME" exec "$c" test -L /var/lib/agentainer/active; then
	fail "container starts"
	finish
	exit 1
fi
pass "container starts on $("$RUNTIME" exec "$c" uname -m)"

# pin NAME PACKAGE: the version the catalog's wrapper package.json pins.
pin() {
	"$RUNTIME" exec "$c" node -p 'require(process.argv[1]).dependencies[process.argv[2]]' \
		"$catalog/$1/package.json" "$2"
}

# live NAME PACKAGE BIN...: installs NAME and checks that each BIN prints the pinned version.
live() {
	_name=$1 _pkg=$2
	shift 2
	_pin=$(pin "$_name" "$_pkg") || _pin=''
	if [ -z "$_pin" ]; then
		fail "$_name: catalog pins $_pkg"
		return 0
	fi
	if _out=$("$RUNTIME" exec "$c" agentainer-extras install "$_name" 2>&1); then
		assert_contains "$_name: install and its check pass" "installed $_pkg@$_pin" "$_out"
	else
		fail "$_name: install and its check pass" "$_out"
		return 0
	fi
	for _bin; do
		assert_contains "$_name: $_bin --version from PATH prints $_pin" "$_pin" \
			"$("$RUNTIME" exec "$c" sh -c '"$1" --version </dev/null 2>&1' sh "$_bin")"
	done
}

live kandev kandev kandev
# The launcher runs the native runtime from the platform optional dependency.
assert_contains "kandev: the platform runtime package is installed" "runtime-linux-" \
	"$("$RUNTIME" exec "$c" sh -c 'ls '"$ext"'/kandev/node_modules/@kdlbs/ 2>&1')"

live openchamber @openchamber/web openchamber
assert_eq "openchamber: node-pty loads its prebuilt binding" "loaded" \
	"$("$RUNTIME" exec "$c" sh -c 'cd '"$ext"'/openchamber && node -e "require(\"node-pty\"); console.log(\"loaded\")" 2>&1')"

live rea rea-agents rea rea-agents
assert_eq "rea: @lydell/node-pty loads its platform binary" "loaded" \
	"$("$RUNTIME" exec "$c" sh -c 'cd '"$ext"'/rea && node -e "require(\"@lydell/node-pty\"); console.log(\"loaded\")" 2>&1')"
# frida installs as an optional dependency, but its install script, which fetches or builds
# build/frida_binding.node (frida 17.23.2 scripts/install.js), never runs. "frida.js" proves
# the listing ran on an installed frida; any .node file would be a native binding.
assert_absent "rea: frida is installed without a native binding" \
	"$("$RUNTIME" exec "$c" sh -c 'cd '"$ext"'/rea/node_modules/frida && find . -type f \( -name "*.node" -o -name frida.js \) 2>&1')" \
	"frida.js" ".node"
# The same check in a copy of the install without the platform package must fail.
assert_eq "rea: the check fails without @lydell/node-pty-linux-<arch>" "check failed" \
	"$("$RUNTIME" exec "$c" sh -c '
		check=$(sh -c ". '"$catalog"'/rea/extra.conf && printf %s \"\$check\"")
		[ -n "$check" ] || { echo "no check"; exit 0; }
		t=$(mktemp -d) && cp -a '"$ext"'/rea/. "$t"/ &&
			ls -d "$t"/node_modules/@lydell/node-pty-linux-* >/dev/null &&
			rm -rf "$t"/node_modules/@lydell/node-pty-linux-* || { echo "setup failed"; exit 0; }
		if (cd "$t" && sh -c "$check") >/dev/null 2>&1; then echo "check passed"; else echo "check failed"; fi
		rm -rf "$t"')"
finish
