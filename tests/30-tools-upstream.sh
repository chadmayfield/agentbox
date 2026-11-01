#!/bin/sh
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=versions.env
. "$(dirname "$0")/../versions.env"

assert_contains "go version" "go$GO_VERSION " "$(run_in -- go version)"
assert_contains "rustc version" "rustc $RUST_VERSION " "$(run_in -- rustc --version)"
assert_contains "cargo version" "cargo $RUST_VERSION " "$(run_in -- cargo --version)"
assert_eq "clippy and rustfmt installed" "rc=0" "$(run_in -- sh -c 'cargo clippy --version >/dev/null && cargo fmt --version >/dev/null; echo rc=$?')"
assert_eq "cargo builds with a run-time CARGO_HOME" "rc=0" \
	"$(run_in -e CARGO_HOME=/tmp/ch -- sh -c 'cd /tmp && cargo new -q h && cd h && cargo build -q 2>&1 && ./target/debug/h >/dev/null; echo rc=$?')"
assert_contains "yq is mikefarah" "mikefarah" "$(run_in -- yq --version)"
assert_contains "yq version" "v$YQ_VERSION" "$(run_in -- yq --version)"
assert_contains "gh version" "gh version $GH_VERSION " "$(run_in -- gh --version)"
assert_contains "uv version" "uv $UV_VERSION" "$(run_in -- uv --version)"
assert_contains "uvx version" "uvx $UV_VERSION" "$(run_in -- uvx --version)"
assert_eq "ruff version" "ruff $RUFF_VERSION" "$(run_in -- ruff --version)"
assert_contains "trivy version" "Version: $TRIVY_VERSION" "$(run_in -- trivy --version)"
assert_absent "curlie is not bundled" "$(run_in -- sh -c 'command -v curlie; echo CURLIE_CHECK_RAN')" "CURLIE_CHECK_RAN" "curlie"
assert_contains "golangci-lint version" "version $GOLANGCI_LINT_VERSION " "$(run_in -- golangci-lint --version)"
assert_contains "tea version" "$TEA_VERSION" "$(run_in -- tea --version)"
assert_eq "node version" "v$NODE_VERSION" "$(run_in -- node --version)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "node is the upstream build" "/opt/node/bin/node" "$(run_in -- sh -c 'readlink -f "$(command -v node)"')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "npm is the copy bundled with node" "/opt/node/lib/node_modules/npm/bin/npm-cli.js" "$(run_in -- sh -c 'readlink -f "$(command -v npm)"')"
assert_eq "node ships its license" "present" "$(run_in -- sh -c 'test -s /opt/node/LICENSE && echo present')"
# shellcheck disable=SC2016 # expands in the container
# Any package state other than not-installed counts (installed, held, half-installed).
assert_absent "apt nodejs and npm are not installed" \
	"$(run_in -- sh -c 'dpkg-query -W -f="\${Package} \${db:Status-Status}\n" nodejs npm 2>/dev/null; echo DPKG_CHECK_RAN')" \
	DPKG_CHECK_RAN "nodejs installed" "nodejs half-" "nodejs unpacked" "nodejs config-files" "nodejs triggers" "npm installed" "npm half-" "npm unpacked" "npm config-files" "npm triggers"
assert_eq "no apt node binary" "none" "$(run_in -- sh -c 'ls /usr/bin/node 2>/dev/null || echo none')"
assert_eq "npm update notifier is off" "false" "$(run_in -- npm config get update-notifier)"
assert_contains "aws version" "aws-cli/$AWSCLI_VERSION " "$(run_in -- aws --version)"
# shellcheck disable=SC2016 # expands in the container
assert_eq "aws is the official installer's layout" "/usr/local/aws-cli/v2/$AWSCLI_VERSION/dist/aws" \
	"$(run_in -- sh -c 'readlink -f "$(command -v aws)"')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "aws_completer is installed" "/usr/local/aws-cli/v2/$AWSCLI_VERSION/dist/aws_completer" \
	"$(run_in -- sh -c 'readlink -f "$(command -v aws_completer)"')"
# aws help renders its pages with groff (AWS install guide: "The AWS CLI uses glibc, groff,
# and less"). The sed removes groff's bold, as ANSI SGR codes or backspace overstrike,
# before the heading is matched.
# shellcheck disable=SC2016 # expands in the container
assert_eq "aws help renders offline" "rc=0 DESCRIPTION" \
	"$(run_in --network none -- sh -c 'out=$(aws s3 help 2>&1 </dev/null); rc=$?; printf "%s\n" "$out" | sed -e "s/$(printf "\033")\[[0-9;]*m//g" -e "s/.$(printf "\b")//g" | grep -qx DESCRIPTION && h=DESCRIPTION; echo "rc=$rc ${h:-}"')"
assert_eq "no AWS configuration is seeded" "none" "$(run_in -- sh -c 'ls -d ~/.aws /etc/agentainer/seed/.aws 2>/dev/null || echo none')"
assert_eq "no Node headers or docs shipped" "none" "$(run_in -- sh -c 'ls -d /opt/node/include /opt/node/share /opt/node/README.md /opt/node/CHANGELOG.md 2>/dev/null || echo none')"
# find prints END only when it exits 0, so a missing or unreadable path fails these checks
# with find's error message in the output instead of passing on an empty result.
assert_eq "everything under /opt and /usr/local is root-owned" "END" \
	"$(run_in -- sh -c 'find /opt /usr/local -xdev ! -user root ! -type l 2>&1 && echo END')"
assert_eq "nothing under /opt and /usr/local is world-writable" "END" \
	"$(run_in -- sh -c 'find /opt /usr/local -xdev -perm -o+w ! -type l 2>&1 && echo END')"
# shellcheck disable=SC2016 # expands in the container
assert_eq "no Rust docs shipped" "END" \
	"$(run_in -- sh -c 'find "$RUSTUP_HOME/toolchains" -path "*/share/doc" -prune 2>&1 && echo END')"
assert_eq "no build leftovers" "rc=2" "$(run_in -- sh -c 'ls /tmp/agentainer-build 2>/dev/null; echo rc=$?')"

# Go's own test suite and API lists are not needed to build, vet or test code.
assert_eq "no Go test suite or API lists" "none" "$(run_in -- sh -c 'ls -d /usr/local/go/test /usr/local/go/api 2>/dev/null || echo none')"

finish
