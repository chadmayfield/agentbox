#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=versions.env
. "$(dirname "$0")/../versions.env"

# Exact version lines, so a pin of 1.3.2 cannot match 1.3.21.
assert_eq "claude version" "$CLAUDE_CODE_VERSION (Claude Code)" "$(run_in -- claude --version 2>/dev/null)"
assert_eq "codex version" "codex-cli $CODEX_VERSION" "$(run_in -- codex --version 2>/dev/null)"
# agy prints the bare version for --version.
assert_eq "agy version" "$AGY_VERSION" "$(run_in -- agy --version 2>/dev/null)"
assert_eq "opencode version" "opencode v$OPENCODE_VERSION" "$(run_in -- opencode --version 2>/dev/null | tail -1)"

assert_eq "agents run as uid 1000" "1000" "$(run_in -- id -u)"
for b in claude codex agy opencode; do
	p=$(run_in -- sh -c "readlink -f \$(command -v $b)")
	case "$p" in
	/usr/local/* | /opt/*) pass "$b outside home ($p)" ;;
	*) fail "$b outside home" "$p" ;;
	esac
	assert_eq "$b root-owned" "root" "$(run_in -- stat -c %U "$p")"
done
# Claude Code is the native release binary itself, with no npm copy beside it.
assert_eq "claude is the native binary, not a link" "file" \
	"$(run_in -- sh -c 'if [ -f /usr/local/bin/claude ] && [ ! -L /usr/local/bin/claude ]; then echo file; else echo other; fi')"
assert_absent "no npm Claude Code package" \
	"$(run_in -- sh -c 'ls -d /usr/local/lib/node_modules/@anthropic-ai /opt/node/lib/node_modules/@anthropic-ai 2>/dev/null; echo END')" END "@anthropic-ai"
# shellcheck disable=SC2016 # expands in the container
assert_eq "update locks in the environment" "1 true 1 1" \
	"$(run_in -- sh -c 'echo $DISABLE_UPDATES $AGY_CLI_DISABLE_AUTO_UPDATE $OPENCODE_DISABLE_AUTOUPDATE $CLAUDE_CODE_NONBLOCKING_STDOUT')"
# The Codex lock holds even when the user's own config turns the check back on.
assert_eq "codex update check stays off despite user config" "false" \
	"$(run_in --network none -- sh -c 'mkdir -p ~/.codex && echo "check_for_update_on_startup = true" > ~/.codex/config.toml && codex doctor --json 2>/dev/null' | python3 -c 'import sys,json
print(json.load(sys.stdin)["checks"]["updates.status"]["details"]["check for update on startup"])' 2>&1)"
assert_contains "claude update refused by DISABLE_UPDATES" "Updates are disabled by your administrator" \
	"$(run_in --network none -- sh -c 'claude update 2>&1 || true')"
assert_contains "versions.json lists pins" "\"CODEX_VERSION\": \"$CODEX_VERSION\"" "$(run_in -- cat /etc/agentainer/versions.json)"
assert_contains "versions.json lists apt packages" "\"tmux\":" "$(run_in -- cat /etc/agentainer/versions.json)"
assert_eq "source label" "https://github.com/chadmayfield/agentainer" \
	"$("$RUNTIME" image inspect "$IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')"
assert_eq "version label is ours, not the base image's" "rc=0" \
	"$(
		v=$("$RUNTIME" image inspect "$IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
		if [ "$v" != 26.04 ] && [ -n "$v" ]; then echo rc=0; else echo rc=1; fi
	)"

# Codex's voice host needs a microphone, which a container does not have.
assert_eq "no Codex voice resources" "none" "$(run_in -- sh -c 'ls -d /opt/codex/codex-resources/voice 2>/dev/null || echo none')"

finish
