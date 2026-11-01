#!/bin/sh
# shellcheck disable=SC2016 # single-quoted scripts expand in the container
# agentainer-extras against an offline fixture catalog (tests/fixtures/make-extras-catalog.sh)
# served by a loopback registry inside each test container.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
VOL="agentainer-test-extras-home-$$"
c1="agentainer-test-extras-$$-1"
c2="agentainer-test-extras-$$-2"
c3="agentainer-test-extras-$$-3"
c4="agentainer-test-extras-$$-4"
OUT=$(mktemp -d)
"$RUNTIME" volume create "$VOL" >/dev/null
trap '"$RUNTIME" rm -f "$c1" "$c2" "$c3" "$c4" >/dev/null 2>&1; "$RUNTIME" volume rm -f "$VOL" >/dev/null; rm -rf "$OUT"' EXIT
# dash skips the EXIT trap on a signal; exiting from the signal trap runs it.
trap 'exit 130' INT TERM
fixtures="$repo/tests/fixtures:/fixtures:ro"
catalog=/usr/local/share/agentainer/extras
reg=http://127.0.0.1:48731/
A=/var/lib/agentainer/active
# Lists the npm bin and extras directories one name per line in brackets, so a needle such as
# "[fixture]" matches that exact name only.
names='{ ls -a '"$A"'/npm/bin '"$A"'/npm/extras 2>/dev/null | sed "s/^/[/;s/\$/]/"; }'

# start NAME [run options...]: starts a container, builds the fixture catalog in /tmp/fx,
# copies the fixture and fixture-bad entries into the catalog as root, and starts the registry.
start() {
	_c=$1
	shift
	run_bg "$_c" -v "$fixtures" --network none "$@" || return 1
	wait_for 30 "$RUNTIME" exec "$_c" test -L "$A" || return 1
	"$RUNTIME" exec -u 0 "$_c" sh -c 'bash /fixtures/make-extras-catalog.sh /tmp/fx >/dev/null &&
		mkdir -p '"$catalog"' && cp -r /tmp/fx/fixture /tmp/fx/fixture-bad '"$catalog"'/ &&
		chmod -R a+rX '"$catalog"'' || return 1
	"$RUNTIME" exec -d -u 0 "$_c" python3 -m http.server --bind 127.0.0.1 --directory /tmp/fx/registry 48731 >/dev/null
	wait_for 10 "$RUNTIME" exec "$_c" curl -sf "${reg}agentainer-extra-fixture"
}

# ex NAME SCRIPT: runs SCRIPT as the agent in container NAME with the fixture registry.
ex() {
	"$RUNTIME" exec -e NPM_CONFIG_REGISTRY="$reg" "$1" sh -c "$2"
}

# swap NAME ENTRY: replaces the catalog's fixture entry with /tmp/fx/ENTRY.
swap() {
	"$RUNTIME" exec -u 0 "$1" sh -c "rm -rf $catalog/fixture && cp -r /tmp/fx/$2 $catalog/fixture && chmod -R a+rX $catalog/fixture"
}

# assert_same NAME EXPECTED GOT: like assert_eq, but an empty EXPECTED fails, so two
# commands that both failed to run do not compare equal.
assert_same() {
	if [ -z "$2" ]; then fail "$1" "nothing to compare against"; else assert_eq "$1" "$2" "$3"; fi
}

# row NAME: the name, pinned and installed columns of the fixture row from list.
row() {
	ex "$1" 'agentainer-extras list' | awk '$1 == "fixture" { print $1, $2, $3 }'
}

# The command needs the tools root that the entrypoint links.
out=$(run_in --network none --entrypoint sh -- -c 'agentainer-extras list 2>&1; echo "[rc=$?]"')
assert_contains "no tools root: exit 1" "[rc=1]" "$out"
assert_contains "no tools root: names the missing path" "$A" "$out"

# Ephemeral mode.
if start "$c1" -v "$VOL:/home/agent"; then pass "ephemeral container with the fixture catalog"; else fail "ephemeral container with the fixture catalog"; fi

assert_contains "no arguments: exit 2" "[rc=2]" "$(ex "$c1" 'agentainer-extras 2>&1; echo "[rc=$?]"')"
assert_contains "unknown subcommand: exit 2" "[rc=2]" "$(ex "$c1" 'agentainer-extras frob 2>&1; echo "[rc=$?]"')"
assert_eq "list shows the pin and - before install" "fixture 1.0.0 -" "$(row "$c1")"
out=$(ex "$c1" 'agentainer-extras install nosuch 2>&1; echo "[rc=$?]"')
assert_contains "unknown name: exit 2" "[rc=2]" "$out"
assert_contains "unknown name: lists the valid names" "fixture-bad" "$out"
out=$(ex "$c1" 'agentainer-extras install fixture nosuch 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "known and unknown name: exit 2" "[rc=2]" "$out"
assert_absent "known and unknown name: installs nothing" "$out" END "[fixture]" "[fixture-extra]" "[fixture@"

ex "$c1" 'touch /tmp/before-install'
out=$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')
assert_contains "install exits 0" "[rc=0]" "$out"
assert_contains "install prints the notes" "fixture notes" "$out"
assert_contains "ephemeral install says how to keep the tool" "AGENTAINER_TOOLS=persist" "$out"
assert_eq "the installed bin runs" "fixture-extra ok 1.0.0" "$(ex "$c1" 'fixture-extra 2>&1')"
assert_eq "the extras link target is a bare directory name" "ok" \
	"$(ex "$c1" 't=$(readlink '"$A"'/npm/extras/fixture); case $t in */*) echo "slash: $t" ;; fixture@1.0.0.*) echo ok ;; *) echo "bad: $t" ;; esac')"
assert_contains "ephemeral install lands in the image tools root" "/var/lib/agentainer/tools/npm/extras/fixture@1.0.0." \
	"$(ex "$c1" 'readlink -f "$(command -v fixture-extra)"')"
assert_absent "install writes nothing to the npm cache in the home" \
	"$(ex "$c1" 'find /home/agent/.npm -newer /tmp/before-install 2>/dev/null; echo END')" END /home/agent/.npm
assert_eq "list shows the installed version" "fixture 1.0.0 1.0.0" "$(row "$c1")"
assert_eq "the install directory has the tools root's mode" "755" "$(ex "$c1" "stat -c %a $A/npm/extras/\$(readlink $A/npm/extras/fixture)")"

# Upgrade keeps the previous directory and removes it at the next install.
first=$(ex "$c1" "readlink $A/npm/extras/fixture")
assert_contains "the first install is linked" "fixture@1.0.0." "$first"
swap "$c1" fixture-v2
assert_contains "list marks an install that differs from the pin" "fixture 2.0.0 1.0.0 (outdated)" \
	"$(ex "$c1" 'agentainer-extras list' | awk '$1 == "fixture" { print $1, $2, $3, $4 }')"
assert_contains "upgrade exits 0" "[rc=0]" "$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')"
assert_eq "upgrade runs the new version" "fixture-extra ok 2.0.0" "$(ex "$c1" 'fixture-extra 2>&1')"
assert_eq "upgrade keeps the previous directory" "kept" "$(ex "$c1" "test -d $A/npm/extras/$first && echo kept")"
second=$(ex "$c1" "readlink $A/npm/extras/fixture")
assert_contains "reinstall exits 0" "[rc=0]" "$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')"
assert_absent "the next install removes the kept directory" "$(ex "$c1" "$names; echo END")" END "[$first]"
assert_eq "the next install keeps the version it replaced" "kept" "$(ex "$c1" "test -d $A/npm/extras/$second && echo kept")"

# Failed upgrades leave the previous version linked and running, and leave no new directory.
current=$(ex "$c1" "readlink $A/npm/extras/fixture")
assert_contains "the version before the failed upgrades is linked" "fixture@2.0.0." "$current"
before=$(ex "$c1" "$names")
for entry in fixture-bad fixture-v3-mismatch fixture-check-fails; do
	swap "$c1" "$entry"
	out=$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')
	assert_contains "failed upgrade ($entry): exit 1" "[rc=1]" "$out"
	assert_same "failed upgrade ($entry): link unchanged" "$current" "$(ex "$c1" "readlink $A/npm/extras/fixture")"
	assert_eq "failed upgrade ($entry): previous version runs" "fixture-extra ok 2.0.0" "$(ex "$c1" 'fixture-extra 2>&1')"
	assert_same "failed upgrade ($entry): no new directory" "$before" "$(ex "$c1" "$names")"
	case $entry in
	fixture-v3-mismatch) assert_contains "version mismatch names both versions" "3.0.1" "$out" ;;
	esac
done

# omit_optional=no installs optional dependencies even when the user's npm config omits them.
ex "$c1" 'echo omit=optional >~/.npmrc'
swap "$c1" fixture-optional
out=$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"; test -d '"$A"'/npm/extras/fixture/node_modules/agentainer-extra-optional && echo present')
assert_contains "omit_optional=no with omit=optional in ~/.npmrc: exit 0" "[rc=0]" "$out"
assert_contains "omit_optional=no installs the optional dependency" "present" "$out"
swap "$c1" fixture-omit
out=$(ex "$c1" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"; ls '"$A"'/npm/extras/fixture/node_modules; echo END')
assert_contains "omit_optional=yes: exit 0" "[rc=0]" "$out"
assert_absent "omit_optional=yes leaves the optional dependency out" "$out" END agentainer-extra-optional
ex "$c1" 'rm -f ~/.npmrc'

# A held extras lock makes install say what it waits for, then go ahead once it is released.
# The holder runs until /tmp/hold is removed, which happens only after the waiting line shows.
swap "$c1" fixture
ex "$c1" 'touch /tmp/hold; rm -f /tmp/wait.out'
"$RUNTIME" exec -d "$c1" flock "$A/npm/.extras.lock" sh -c 'while [ -e /tmp/hold ]; do sleep 0.2; done'
if wait_for 10 "$RUNTIME" exec "$c1" sh -c "! flock -n $A/npm/.extras.lock true"; then pass "extras lock held"; else fail "extras lock held"; fi
ex "$c1" 'agentainer-extras install fixture >/tmp/wait.out 2>&1; echo "[rc=$?]" >>/tmp/wait.out' &
if wait_for 60 "$RUNTIME" exec "$c1" grep -q "waiting for" /tmp/wait.out; then pass "install prints a waiting line"; else fail "install prints a waiting line"; fi
ex "$c1" 'rm -f /tmp/hold'
wait
out=$(ex "$c1" 'cat /tmp/wait.out')
assert_contains "install waits for a held lock and names it" "waiting for $A/npm/.extras.lock" "$out"
assert_contains "install finishes after the lock is free" "[rc=0]" "$out"

# Remove.
out=$(ex "$c1" 'agentainer-extras remove fixture 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "remove exits 0" "[rc=0]" "$out"
assert_contains "remove says user data was left" "left in place" "$out"
assert_absent "remove deletes the bin link, the link and the directories" "$out" END "[fixture]" "[fixture-extra]" "[fixture@"

# A tarball whose bytes differ from the lockfile is refused on a clean root.
out=$(ex "$c1" 'agentainer-extras install fixture-bad 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "changed tarball bytes: exit 1" "[rc=1]" "$out"
assert_absent "changed tarball bytes: no bin and no directory" "$out" END "[fixture-extra]" "[fixture-bad"
log=$(printf '%s\n' "$out" | sed -n "s/.*npm's log is in //p")
assert_eq "a failed npm ci keeps npm's log and names it" "has a log" "$(ex "$c1" "[ -n '$log' ] && [ -n \"\$(ls '$log')\" ] && echo 'has a log'")"

# install A B: B fails, A stays installed.
out=$(ex "$c1" 'agentainer-extras install fixture fixture-bad 2>&1; echo "[rc=$?]"')
assert_contains "install A B with B failing: exit 1" "[rc=1]" "$out"
assert_eq "install A B with B failing: A installed" "fixture-extra ok 1.0.0" "$(ex "$c1" 'fixture-extra 2>&1')"
ex "$c1" 'agentainer-extras remove fixture' >/dev/null 2>&1

# A file the user put at a bin path is never replaced.
out=$(ex "$c1" 'echo mine >'"$A"'/npm/bin/fixture-extra; agentainer-extras install fixture 2>&1; echo "[rc=$?]"; cat '"$A"'/npm/bin/fixture-extra; '"$names"'; echo END')
assert_contains "a different file at the bin path: exit 1" "[rc=1]" "$out"
assert_contains "a different file at the bin path: names it" "$A/npm/bin/fixture-extra" "$out"
assert_contains "a different file at the bin path: left as it was" "mine" "$out"
assert_absent "a different file at the bin path: nothing installed" "$out" END "[fixture]" "[fixture@"
ex "$c1" "rm -f $A/npm/bin/fixture-extra"

# A failure at the NAME link switch leaves no bin link from that run.
out=$(ex "$c1" 'mkdir '"$A"'/npm/extras/fixture; agentainer-extras install fixture 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "a failed link switch: exit 1" "[rc=1]" "$out"
assert_absent "a failed link switch: no bin link and no new directory" "$out" END "[fixture-extra]" "[fixture@"
ex "$c1" "rmdir $A/npm/extras/fixture"

# remove works for an installed extra that is absent from the catalog; a name that is
# neither is unknown.
ex "$c1" 'agentainer-extras install fixture' >/dev/null 2>&1
"$RUNTIME" exec -u 0 "$c1" rm -rf "$catalog/fixture"
out=$(ex "$c1" 'agentainer-extras remove fixture 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "remove of an extra dropped from the catalog: exit 0" "[rc=0]" "$out"
assert_absent "remove of an extra dropped from the catalog: links and directories gone" "$out" END "[fixture]" "[fixture-extra]" "[fixture@"
assert_contains "remove of an unknown name: exit 2" "[rc=2]" "$(ex "$c1" 'agentainer-extras remove nosuch 2>&1; echo "[rc=$?]"')"
swap "$c1" fixture

# A name absent from the catalog with only versioned directories left behind can be removed.
out=$(ex "$c1" 'mkdir -p '"$A"'/npm/extras/ghost@1.0.0.abc123; agentainer-extras remove ghost 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "remove of leftover directories absent from the catalog: exit 0" "[rc=0]" "$out"
assert_absent "remove of leftover directories absent from the catalog: directories gone" "$out" END "[ghost@"

# install and list refuse extra.conf entries that break its rules.
for bad in key bins pkg-path pkg-dots multiline; do
	case $bad in
	key) line='name=x' ;;
	bins) line='bins="*"' ;;
	pkg-path) line='package=../x' ;;
	pkg-dots) line='package=..' ;;
	multiline) line='notes="one
two"' ;;
	esac
	"$RUNTIME" exec -u 0 "$c1" sh -c 'mkdir -p "$1/$2" && cp /tmp/fx/fixture/package.json /tmp/fx/fixture/package-lock.json /tmp/fx/fixture/extra.conf "$1/$2/" &&
		printf "%s\n" "$3" >>"$1/$2/extra.conf" && chmod -R a+rX "$1/$2"' sh "$catalog" "bad-$bad" "$line"
	out=$(ex "$c1" 'agentainer-extras install bad-'"$bad"' 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
	assert_contains "invalid extra.conf ($bad): install exits 1" "[rc=1]" "$out"
	assert_absent "invalid extra.conf ($bad): nothing installed" "$out" END "[bad-$bad" "[fixture-extra]"
	assert_contains "invalid extra.conf ($bad): list marks it" "invalid catalog entry" \
		"$(ex "$c1" 'agentainer-extras list 2>/dev/null' | awk -v n="bad-$bad" '$1 == n')"
	"$RUNTIME" exec -u 0 "$c1" rm -rf "$catalog/bad-$bad"
done

# check runs with stdin closed: data piped into the command does not reach it.
"$RUNTIME" exec -u 0 "$c1" sh -c "cp -r /tmp/fx/fixture-stdin $catalog/ && chmod -R a+rX $catalog/fixture-stdin"
out=$(ex "$c1" 'echo data | agentainer-extras install fixture-stdin 2>&1; echo "[rc=$?]"; '"$names"'; echo END')
assert_contains "check gets no stdin: exit 1" "[rc=1]" "$out"
assert_contains "check gets no stdin: the check is what failed" "the check 'read -r x' failed" "$out"
assert_absent "check gets no stdin: nothing installed" "$out" END "[fixture-stdin" "[fixture-extra]"
"$RUNTIME" exec -u 0 "$c1" rm -rf "$catalog/fixture-stdin"

# A lock file that cannot be opened is a failed install, not a usage error.
out=$(ex "$c1" 'rm -f '"$A"'/npm/.extras.lock && mkdir '"$A"'/npm/.extras.lock; agentainer-extras install fixture 2>&1; echo "[rc=$?]"; rmdir '"$A"'/npm/.extras.lock')
assert_contains "an unopenable lock file: exit 1" "[rc=1]" "$out"
assert_contains "an unopenable lock file: names it" "cannot open the lock file $A/npm/.extras.lock" "$out"

# Ephemeral installs are gone in a new container.
ex "$c1" 'agentainer-extras install fixture' >/dev/null 2>&1
"$RUNTIME" rm -f "$c1" >/dev/null
assert_absent "ephemeral install gone in a new container" \
	"$(run_in -v "$VOL:/home/agent" --network none -- sh -c "$names; command -v fixture-extra; echo END")" END "[fixture]" "fixture-extra"

# Persist mode.
if start "$c2" -v "$VOL:/home/agent" -e AGENTAINER_TOOLS=persist; then pass "persist container with the fixture catalog"; else fail "persist container with the fixture catalog"; fi
out=$(ex "$c2" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')
assert_contains "persist install exits 0" "[rc=0]" "$out"
assert_absent "persist install prints no ephemeral hint" "$out" "[rc=0]" "AGENTAINER_TOOLS=persist"
assert_contains "persist install lands in the home tools root" "/home/agent/.agentainer/tools/npm/extras/fixture@1.0.0." \
	"$(ex "$c2" 'readlink -f "$(command -v fixture-extra)"')"
"$RUNTIME" rm -f "$c2" >/dev/null
assert_eq "persist install survives a new container" "fixture-extra ok 1.0.0" \
	"$(run_in -v "$VOL:/home/agent" --network none -e AGENTAINER_TOOLS=persist -- fixture-extra 2>&1)"

# Two containers on one persist root install at the same time.
start "$c3" -v "$VOL:/home/agent" -e AGENTAINER_TOOLS=persist || fail "third container"
start "$c4" -v "$VOL:/home/agent" -e AGENTAINER_TOOLS=persist || fail "fourth container"
ex "$c3" 'agentainer-extras remove fixture' >/dev/null 2>&1
for c in "$c3" "$c4"; do
	{
		ex "$c" 'agentainer-extras install fixture' >"$OUT/$c.out" 2>&1
		echo "$?" >"$OUT/$c.rc"
	} &
done
wait
assert_eq "concurrent installs both exit 0" "0 0" "$(cat "$OUT/$c3.rc") $(cat "$OUT/$c4.rc")"
assert_eq "concurrent installs: the bin runs in both containers" "fixture-extra ok 1.0.0 fixture-extra ok 1.0.0" \
	"$(ex "$c3" 'fixture-extra') $(ex "$c4" 'fixture-extra')"
assert_eq "concurrent installs: two versioned directories, one linked" "2 yes" \
	"$(ex "$c3" "ls -d $A/npm/extras/fixture@* | wc -l | tr -d ' '; test -d $A/npm/extras/\$(readlink $A/npm/extras/fixture) && echo yes" | tr '\n' ' ' | sed 's/ $//')"

# Reset moves the root, links inside the backup still resolve, and a fresh install works.
out=$(ex "$c3" 'agentainer-tools reset 2>&1')
dest=$(printf '%s\n' "$out" | sed -n 's/^moved .* to //p')
assert_contains "reset names its backup" "/home/agent/.agentainer/tools." "$dest"
assert_contains "after reset the bin link resolves inside the backup" "$dest/npm/extras/fixture@1.0.0." \
	"$(ex "$c3" "readlink -f $dest/npm/bin/fixture-extra")"
assert_eq "after reset the backup bin runs" "fixture-extra ok 1.0.0" "$(ex "$c3" "$dest/npm/bin/fixture-extra")"
assert_contains "install after reset exits 0" "[rc=0]" "$(ex "$c3" 'agentainer-extras install fixture 2>&1; echo "[rc=$?]"')"
assert_eq "install after reset runs" "fixture-extra ok 1.0.0" "$(ex "$c4" 'fixture-extra 2>&1')"

# In persist mode the reset lock is the one next to the tools root, whatever HOME says.
ex "$c3" 'touch /tmp/hold'
"$RUNTIME" exec -d "$c3" flock /home/agent/.agentainer/.tools-reset.lock sh -c 'while [ -e /tmp/hold ]; do sleep 0.2; done'
if wait_for 10 "$RUNTIME" exec "$c4" sh -c '! flock -n /home/agent/.agentainer/.tools-reset.lock true'; then pass "reset lock held for the HOME test"; else fail "reset lock held for the HOME test"; fi
ex "$c4" 'mkdir -p /tmp/h; rm -f /tmp/wait.out; HOME=/tmp/h agentainer-extras install fixture >/tmp/wait.out 2>&1; echo "[rc=$?]" >>/tmp/wait.out' &
if wait_for 60 "$RUNTIME" exec "$c4" grep -q "waiting for" /tmp/wait.out; then pass "install with another HOME waits for the reset lock"; else fail "install with another HOME waits for the reset lock"; fi
ex "$c3" 'rm -f /tmp/hold'
wait
out=$(ex "$c4" 'cat /tmp/wait.out')
assert_contains "install with another HOME names the reset lock next to the root" "waiting for /home/agent/.agentainer/.tools-reset.lock" "$out"
assert_contains "install with another HOME finishes" "[rc=0]" "$out"

# Reset reports a reset lock that another container holds.
"$RUNTIME" exec -d "$c3" flock /home/agent/.agentainer/.tools-reset.lock sleep 45
if wait_for 10 "$RUNTIME" exec "$c4" sh -c '! flock -n /home/agent/.agentainer/.tools-reset.lock true'; then pass "reset lock held"; else fail "reset lock held"; fi
out=$(ex "$c4" 'agentainer-tools reset 2>&1; echo "[rc=$?]"')
assert_contains "reset with a held lock: exit 1" "[rc=1]" "$out"
assert_contains "reset with a held lock: names the lock" "/home/agent/.agentainer/.tools-reset.lock" "$out"

finish
