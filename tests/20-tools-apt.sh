#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"

# shellcheck disable=SC2016 # expands in the container
out=$(run_in -- bash -c '
for c in ssh tmux rsync git git-lfs git-flow git-filter-repo rg fd fzf bat eza vim nano \
  ctags patch diff jq sqlite3 pgcli psql make gcc cmake ninja pkg-config python3 pipx node npm shellcheck shfmt curl wget \
  http nc ip ping dig unzip zip zstd xz 7z exiftool cloc asciinema age ansible oras \
  bwrap htop tree file less sudo; do
  command -v "$c" >/dev/null 2>&1 || echo "MISSING $c"
done
echo DONE')
assert_eq "all apt tools on PATH" "DONE" "$out"
# ping needs no capability: its file capability is removed and the runtime allows
# unprivileged ICMP sockets through net.ipv4.ping_group_range.
assert_contains "ping works without NET_RAW" "1 received" \
	"$(run_in --sysctl 'net.ipv4.ping_group_range=1000 1000' -- ping -c1 -W2 127.0.0.1 2>&1)"
assert_contains "fd runs" "fd" "$(run_in -- fd --version)"
assert_contains "bat runs" "bat" "$(run_in -- bat --version)"
assert_contains "python is 3.14" "Python 3.14" "$(run_in -- python3 --version)"
assert_contains "tmux runs" "tmux 3.6" "$(run_in -- tmux -V)"
assert_contains "pip --user is refused (PEP 668)" "externally-managed" "$(run_in -- sh -c 'python3 -m pip install --user requests 2>&1 || true')"

# ansible-core only: the commands without the 450 MB of bundled collections.
assert_eq "ansible-core without bundled collections" "none" "$(run_in -- sh -c 'ls -d /usr/lib/python3/dist-packages/ansible_collections 2>/dev/null || echo none')"
# Builds a collection in the container and installs the tarball with no network.
assert_eq "ansible-galaxy installs collections" "agentainer.fixture 1.0.0" "$(run_in --network none -- sh -c '
	set -e
	ansible-galaxy collection init agentainer.fixture --init-path /tmp/c >/dev/null
	ansible-galaxy collection build /tmp/c/agentainer/fixture --output-path /tmp/b >/dev/null
	ansible-galaxy collection install --offline /tmp/b/agentainer-fixture-1.0.0.tar.gz >/dev/null
	ansible-galaxy collection list agentainer.fixture --format json |
		python3 -c "import json, sys; print(*(n + \" \" + c[\"version\"] for p in json.load(sys.stdin).values() for n, c in p.items()))"
' 2>&1)"

assert_eq "openssl headers installed" "yes" "$(run_in -- sh -c 'test -f /usr/include/openssl/ssl.h && echo yes')"

finish
