#!/bin/sh
# Builds with a non-default UID and an existing GID (20 is "dialout" in Ubuntu and
# "staff" on macOS) and checks the agent user. Slow: it builds a full image.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/../lib.sh"
cd "$(dirname "$0")/../.." || exit 2
tag=localhost/cx-agentainer:test-uid-$$
log=$(mktemp) || exit 2
trap '"$RUNTIME" rmi -f "$tag" >/dev/null 2>&1; rm -f "$log"' EXIT
trap 'exit 130' INT TERM
if RUNTIME="$RUNTIME" sh scripts/build.sh --uid 1001 --gid 20 --tag "$tag" >"$log" 2>&1; then
	pass "builds with --uid 1001 --gid 20"
else
	fail "builds with --uid 1001 --gid 20" "last 80 lines of the build:"
	tail -n 80 "$log" | awk '{ print "  # " $0 }'
	finish
	exit 1
fi
IMAGE=$tag
assert_eq "uid is 1001" "1001" "$(run_in --name "cx-build-uid-$$" -- id -u)"
assert_eq "gid is 20" "20" "$(run_in --name "cx-build-uid-$$" -- id -g)"
assert_eq "user is agent" "agent" "$(run_in --name "cx-build-uid-$$" -- id -un)"
assert_eq "home is owned by uid 1001" "1001" "$(run_in --name "cx-build-uid-$$" -- stat -c %u /home/agent)"
"$RUNTIME" rmi -f "$tag" >/dev/null 2>&1
finish
