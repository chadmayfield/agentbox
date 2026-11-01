#!/bin/sh
# shellcheck disable=SC2086 # H holds "-v vol:/home/agent" on purpose
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
VOL="agentainer-test-home-$$"
lockname="agentainer-test-lock-$$"
syncname="agentainer-test-sync-$$"
"$RUNTIME" volume create "$VOL" >/dev/null
trap '"$RUNTIME" rm -f "$lockname" "$syncname" >/dev/null 2>&1; "$RUNTIME" volume rm -f "$VOL" >/dev/null' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
H="-v $VOL:/home/agent"

run_in $H --entrypoint sh -- -c 'mkdir -p ~/.agentainer && printf "%s" "{\"mcpServers\":{\"everything\":{\"command\":\"npx\",\"args\":[\"-y\",\"@modelcontextprotocol/server-everything\"]},\"web\":{\"url\":\"https://mcp.example.com/mcp\",\"headers\":{\"Authorization\":\"Bearer \${WEB_TOKEN}\"}}}}" > ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H --network none -- agentainer-mcp list 2>/dev/null)
for a in claude codex opencode agy; do
	assert_contains "$a has the managed servers" "$a: everything, web" "$out"
done
assert_contains "claude sees it" "everything" "$(run_in $H --network none -- claude mcp list 2>/dev/null)"
assert_contains "codex sees it" "everything" "$(run_in $H --network none -- codex mcp list 2>/dev/null)"
# "opencode mcp list" shows servers with their live status and lists none offline;
# the resolved config is what OpenCode loads.
assert_contains "opencode sees it" '"everything"' "$(run_in $H --network none -- opencode debug config 2>/dev/null)"
assert_contains "agy sees it" "everything" "$(run_in $H --network none -- agy mcp list 2>/dev/null)"
assert_contains "codex uses the bearer env var" 'bearer_token_env_var = "WEB_TOKEN"' "$(run_in $H -- cat /home/agent/.codex/config.toml 2>/dev/null)"

# Removing a server from mcp.json removes it everywhere on the next start.
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"web\":{\"url\":\"https://mcp.example.com/mcp\"}}}" > ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H --network none -- sh -c 'claude mcp list && codex mcp list && opencode debug config && agy mcp list && echo LISTED' 2>/dev/null)
assert_contains "the server still in mcp.json stays" "web" "$out"
assert_absent "removed server is gone from every agent" "$out" LISTED everything

# The unit tests again, on the image's Python, where the real TOML parser checks Codex output.
repo=$(cd "$(dirname "$0")/.." && pwd)
assert_contains "MCP unit tests pass on the image's Python (tomllib)" "OK" \
	"$("$RUNTIME" run --rm --pull=never --network none -v "$repo:/src:ro" -w /src --entrypoint python3 "$IMAGE" -m unittest tests.unit.test_mcp_sync 2>&1 | grep -E '^(OK|FAILED)')"

# A user's own Codex settings after agentainer's block survive a re-sync, and Codex still loads the file.
run_in $H --entrypoint sh -- -c 'printf "\n[profiles.mine] # mine\nmodel = \"keepme\"\n" >> ~/.codex/config.toml' >/dev/null
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"web2\":{\"url\":\"https://mcp.example.com/mcp\"}}}" > ~/.agentainer/mcp.json' >/dev/null
assert_contains "user Codex settings survive" 'model = "keepme"' "$(run_in $H -- cat /home/agent/.codex/config.toml 2>/dev/null)"
assert_eq "Codex still loads its config" "ok" \
	"$(run_in $H --network none -- sh -c 'codex --strict-config doctor --json 2>/dev/null' | python3 -c 'import sys,json; print(json.load(sys.stdin)["checks"]["config.load"]["status"])' 2>&1)"

# Deleting mcp.json removes every managed server on the next start.
run_in $H --entrypoint sh -- -c 'rm ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H --network none -- sh -c 'claude mcp list && codex mcp list && opencode debug config && agy mcp list && echo LISTED' 2>/dev/null)
assert_absent "deleting mcp.json removes managed servers" "$out" LISTED web2
assert_eq "user Codex settings survive the removal" "1" "$(run_in $H -- grep -c keepme /home/agent/.codex/config.toml 2>/dev/null)"

# SSE servers reach Claude as SSE; Codex and agy cannot use them and say so.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --entrypoint sh -- -c 'mkdir -p ~/.agentainer && printf "%s" "{\"mcpServers\":{\"ev\":{\"type\":\"sse\",\"url\":\"https://mcp.example.com/sse\",\"cwd\":\"/tmp\"}}}" > ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H --network none -- agentainer-entrypoint claude mcp get ev 2>&1)
assert_contains "claude gets an SSE server as sse" "Type: sse" "$out"
assert_contains "codex warns about SSE" "codex: ev uses SSE" "$out"
assert_contains "agy warns about SSE" "agy: ev uses SSE" "$out"
assert_contains "unknown keys warn" "ev: cwd not supported" "$out"

# A user-scope Claude server the user added is left alone. A local-scope server for
# /workspace (the working directory at startup) with the name of a managed one is no
# conflict: only user scope counts.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --network none --entrypoint sh -- -c 'claude mcp add-json mine "{\"type\":\"stdio\",\"command\":\"theirs\"}" --scope user >/dev/null; cd /workspace && claude mcp add-json proj "{\"type\":\"stdio\",\"command\":\"theirs\"}" --scope local >/dev/null; mkdir -p ~/.agentainer && printf "%s" "{\"mcpServers\":{\"mine\":{\"command\":\"ours\"},\"proj\":{\"command\":\"ours\"}}}" > ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H --network none -w /workspace -- agentainer-entrypoint sh -c 'cd /tmp && claude mcp get mine' 2>&1)
assert_contains "claude: user's own server is reported" "claude already has a server named mine" "$out"
assert_absent "claude: user's own server is kept" "$out" "Command: theirs" "Command: ours"
out=$(run_in $H --network none -- sh -c 'cd /tmp && claude mcp get proj' 2>&1)
assert_absent "claude: a local-scope server in /workspace is no conflict" "$out" "Scope: User config" "Command: theirs"
assert_contains "claude: managed server added at user scope" "Command: ours" "$out"

# Containers sharing one home volume take turns running the sync.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
run_in $H --entrypoint sh -- -c 'mkdir -p ~/.agentainer && printf "%s" "{\"mcpServers\":{\"w\":{\"url\":\"https://mcp.example.com/mcp\"}}}" > ~/.agentainer/mcp.json' >/dev/null
# The test holds the lock from one container until it creates a release file, then starts
# a second container whose startup sync must block on the lock and write nothing until then.
held() { "$RUNTIME" exec "$lockname" test -e /home/agent/.agentainer/held; }
# The sync process opens the shared lock before waiting; it writes nothing until acquired.
sync_blocked() {
	"$RUNTIME" exec "$syncname" sh -c 'for p in $(pgrep -f "[a]gentainer-mcp sync --if-changed"); do readlink /proc/$p/fd/* 2>/dev/null; done' | grep -q '/\.mcp-sync\.lock$'
}
"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --name "$lockname" $H --entrypoint sh "$IMAGE" -c \
	'cd ~/.agentainer && flock .mcp-sync.lock sh -c "touch held; until [ -e release ]; do sleep 0.2; done"' >/dev/null
wait_for 30 held || fail "the test holds the sync lock" "no held file"
"$RUNTIME" run -d --pull=never ${PLATFORM:+--platform "$PLATFORM"} --name "$syncname" $H --network none "$IMAGE" true >/dev/null
if wait_for 60 sync_blocked; then pass "sync waits for another container's sync"; else fail "sync waits for another container's sync" "no sync process waiting on .mcp-sync.lock"; fi
assert_eq "the waiting sync wrote nothing while the lock was held" "absent" \
	"$("$RUNTIME" exec "$lockname" sh -c 'test -e ~/.agentainer/mcp-managed.json && echo present || echo absent' 2>&1)"
"$RUNTIME" exec "$lockname" touch /home/agent/.agentainer/release
assert_eq "the waiting sync finished after the release" "0" "$("$RUNTIME" wait "$syncname" 2>&1)"
"$RUNTIME" rm -f "$lockname" "$syncname" >/dev/null 2>&1
assert_contains "the waiting sync still ran" "claude: w" "$(run_in $H --network none -- agentainer-mcp list 2>/dev/null)"

# Codex rewrites config.toml: "codex plugin add" puts its tables between our markers and
# "codex mcp add" drops the begin marker. A later sync must keep both. A fresh volume
# keeps our block at the end of the file, where Codex puts its new tables inside it.
# Codex records the marketplace path, so every container mounts the fixture at /fx.
"$RUNTIME" volume rm -f "$VOL" >/dev/null
"$RUNTIME" volume create "$VOL" >/dev/null
FX="$repo/tests/fixtures/codex-marketplace:/fx:ro"
run_in $H --entrypoint sh -- -c 'mkdir -p ~/.agentainer && printf "%s" "{\"mcpServers\":{\"w\":{\"url\":\"https://mcp.example.com/a\"}}}" > ~/.agentainer/mcp.json' >/dev/null
installed='codex plugin list --json | python3 -c "import json, sys; print(\"installed:\", *[p[\"pluginId\"] for p in json.load(sys.stdin)[\"installed\"] if p[\"installed\"]])"'
# Where Codex put things relative to our markers, to prove the case this test needs.
layout() {
	run_in $H --network none --entrypoint python3 -- -c 'import pathlib
t = pathlib.Path.home().joinpath(".codex/config.toml").read_text()
b, e = t.find("# >>> agentainer-mcp"), t.find("# <<< agentainer-mcp <<<")
inside = lambda s: 0 <= t.find(s) < e and t.find(s) > b
print("begin=%d plugin-inside=%s mine-before-end=%s" % (t.count("# >>> agentainer-mcp"), inside("[plugins."), 0 <= t.find("[mcp_servers.mine]") < e))' 2>&1
}
out=$(run_in $H -v "$FX" --network none -- sh -c "codex plugin marketplace add /fx/fixture-market && codex plugin add fixture-plugin@fixture-market --json >/dev/null && $installed" 2>&1)
assert_contains "codex installs a plugin from the offline fixture" "installed: fixture-plugin@fixture-market" "$out"
assert_contains "codex put its plugin tables inside our block" "begin=1 plugin-inside=True" "$(layout)"
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"w\":{\"url\":\"https://mcp.example.com/b\"}}}" > ~/.agentainer/mcp.json' >/dev/null
# The entrypoint syncs the changed mcp.json first; a direct sync runs again on the same input.
out=$(run_in $H -v "$FX" --network none -- sh -c "agentainer-mcp sync; echo sync=\$?; $installed; codex mcp list" 2>&1)
assert_contains "the sync after codex plugin add succeeds" "sync=0" "$out"
assert_contains "the Codex plugin survives the sync" "installed: fixture-plugin@fixture-market" "$out"
assert_contains "codex has the updated managed server" "https://mcp.example.com/b" "$out"
# Then a server added with "codex mcp add", which removes the begin marker.
run_in $H -v "$FX" --network none -- sh -c 'codex mcp add mine -- echo hi' >/dev/null 2>&1
assert_contains "codex mcp add removed the begin marker" "begin=0" "$(layout)"
assert_contains "codex put the user's server before the end marker" "mine-before-end=True" "$(layout)"
run_in $H --entrypoint sh -- -c 'printf "%s" "{\"mcpServers\":{\"w\":{\"url\":\"https://mcp.example.com/c\"}}}" > ~/.agentainer/mcp.json' >/dev/null
out=$(run_in $H -v "$FX" --network none -- sh -c "agentainer-mcp sync; echo sync=\$?; $installed; codex mcp list" 2>&1)
assert_contains "the sync after codex mcp add succeeds" "sync=0" "$out"
assert_contains "the plugin survives the second sync" "installed: fixture-plugin@fixture-market" "$out"
assert_contains "the user's codex mcp add server survives" "mine " "$out"
assert_contains "codex has the managed server's second update" "https://mcp.example.com/c" "$out"
out=$(run_in $H --network none --entrypoint python3 -- -c 'import pathlib, tomllib
t = pathlib.Path.home().joinpath(".codex/config.toml").read_text()
b, e = "# >>> agentainer-mcp", "# <<< agentainer-mcp <<<"
block = t[t.index(b):t.index(e)]
d = tomllib.loads(t)
print("markers:", t.count(b), t.count(e), "in-block:", "[plugins." in block, "[marketplaces." in block, "[mcp_servers.mine]" in block,
      "servers:", sorted(d["mcp_servers"]), "plugin:", d["plugins"]["fixture-plugin@fixture-market"]["enabled"])' 2>&1)
assert_eq "codex tables sit outside one marker pair" \
	"markers: 1 1 in-block: False False False servers: ['mine', 'w'] plugin: True" "$out"

# A malformed file keeps the container up.
assert_contains "malformed file keeps the container up" "ok" \
	"$(run_in $H --entrypoint sh -- -c 'echo "{bad" > ~/.agentainer/mcp.json; agentainer-entrypoint echo ok 2>/dev/null')"

finish
