#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

assert_eq "raw image permits container sudo" "0" "$(run_in --network none -- sudo -n id -u)"
# shellcheck disable=SC2016 # expands inside the container
assert_eq "no-new-privileges blocks sudo" "SUDO_BLOCKED" \
	"$(run_in --network none --security-opt no-new-privileges=true -- sh -c 'if sudo -n true 2>/dev/null; then echo SUDO_ALLOWED; else echo SUDO_BLOCKED; fi')"

# sudo drops NPM_CONFIG_PREFIX, so root's npm uses the prefix from npm's builtin config.
repo=$(cd "$(dirname "$0")/.." && pwd)
fixtures="$repo/tests/fixtures:/fixtures:ro"
assert_eq "agent npm prefix is the tools root" "/var/lib/agentainer/active/npm" "$(run_in --network none -- npm config get prefix)"
assert_eq "sudo npm prefix is /usr/local" "/usr/local" "$(run_in --network none -- sudo -n npm config get prefix)"
# shellcheck disable=SC2016 # expands inside the container
assert_eq "sudo npm -g installs into /usr/local/bin" "/usr/local/bin/fixture-npm fixture-npm ok" \
	"$(run_in --network none -v "$fixtures" -- sh -c 'fx=$(bash /fixtures/make-tools.sh) && sudo -n npm install -g --offline --no-fund --no-audit "$fx/fixture.tgz" >/dev/null 2>&1; test -x /usr/local/bin/fixture-npm && echo "/usr/local/bin/fixture-npm $(/usr/local/bin/fixture-npm)"')"
finish
