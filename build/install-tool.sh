#!/bin/bash
# Installs one tool into its final path inside a build stage: install-tool.sh NAME.
# Each Containerfile stage passes only that tool's pins from versions.env as build
# arguments, so a bump of one tool rebuilds only its stage. Every download is checked
# against a pin before it is used (fetch.sh). rustup-init downloads the Rust components
# itself; check_rust_manifest ties them to the pinned channel manifest.
set -euo pipefail
F=/usr/local/lib/agentainer-build/fetch.sh
case "${TARGETARCH:?}" in
amd64)
	A=AMD64
	TRIPLE=x86_64
	TRIVY_ARCH=64bit
	OC=linux-x64-baseline
	CLAUDE_PLATFORM=linux-x64
	NODE_ARCH=x64
	;;
arm64)
	A=ARM64
	TRIPLE=aarch64
	TRIVY_ARCH=ARM64
	OC=linux-arm64
	CLAUDE_PLATFORM=linux-arm64
	NODE_ARCH=arm64
	;;
*)
	echo "unsupported arch $TARGETARCH" >&2
	exit 1
	;;
esac
# pin NAME: the value of the build argument NAME_<arch>, for example GO_SHA256_ARM64.
pin() {
	local v="$1_$A"
	printf '%s' "${!v}"
}
# check_rust_manifest PINNED SHA256 USED UPDATE_HASH: fails unless rustup installed from
# the channel manifest PINNED, whose SHA-256 is SHA256. rustup checks each component
# against the manifest it downloads itself, so this ties that manifest to the pin:
# - USED is the copy rustup keeps in the toolchain (lib/rustlib/
#   multirust-channel-manifest.toml). rustup writes it re-serialized, so its bytes differ
#   from PINNED; every url, hash, xz_url and xz_hash in it must equal the same key in
#   PINNED.
# - UPDATE_HASH is RUSTUP_HOME/update-hashes/<toolchain>. rustup writes the first 20 hex
#   digits of its manifest's SHA-256 there (UPDATE_HASH_LEN in src/dist/download.rs),
#   so only that prefix can be compared with SHA256.
check_rust_manifest() {
	local stored
	stored=$(cat "$4") || return 1
	if [ "$stored" != "${2:0:20}" ]; then
		echo "install-tool.sh: rustup used a manifest with hash $stored, pinned $2" >&2
		return 1
	fi
	python3 - "$1" "$3" <<'EOF'
import re
import sys

KEY = re.compile(r'^(url|hash|xz_url|xz_hash) = "([^"]*)"$')


def entries(path):
    out, table = {}, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("["):
                table = line
                continue
            m = KEY.match(line)
            if m and table:
                out[(table, m.group(1))] = m.group(2)
    return out


pinned, used = entries(sys.argv[1]), entries(sys.argv[2])
if not any(key in ("hash", "xz_hash") for _, key in used):
    sys.exit("install-tool.sh: no component hashes in %s" % sys.argv[2])
bad = sorted(k for k, v in used.items() if pinned.get(k) != v)
for table, key in bad:
    print("install-tool.sh: %s %s differs from the pinned manifest" % (table, key), file=sys.stderr)
sys.exit(1 if bad else 0)
EOF
}

# rustup appends component names as concurrent downloads finish. Their order has no
# meaning when rustup reads them, so use stable bytes for the exported tool layer.
# https://github.com/rust-lang/rustup/blob/1.29.1/src/dist/component/components.rs
normalize_rust_components() {
	local tmp
	tmp=$(mktemp) || return 1
	if ! LC_ALL=C sort "$1" >"$tmp"; then
		rm -f "$tmp"
		return 1
	fi
	# Write through the existing file so sort implementations that replace -o's
	# destination cannot change its owner or permissions.
	if ! cat "$tmp" >"$1"; then
		rm -f "$tmp"
		return 1
	fi
	rm -f "$tmp"
}

W=$(mktemp -d)
cd "$W"

case "${1:?usage: install-tool.sh NAME}" in
go)
	# https://go.dev/dl/
	sh $F "https://go.dev/dl/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz" sha256 "$(pin GO_SHA256)" go.tgz
	tar -C /usr/local -xzf go.tgz
	# go build, vet, test and doc do not use Go's own test suite or API lists (29 MB).
	rm -rf /usr/local/go/test /usr/local/go/api
	;;
rust)
	# rustup-init from https://static.rust-lang.org/rustup/archive/
	sh $F "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${TRIPLE}-unknown-linux-gnu/rustup-init" sha256 "$(pin RUSTUP_SHA256)" rustup-init
	chmod +x rustup-init
	# The channel manifest lists the SHA-256 of every component. rustup-init downloads
	# its own copy and checks each component against it; check_rust_manifest then
	# compares that copy with this pinned one.
	sh $F "https://static.rust-lang.org/dist/channel-rust-${RUST_VERSION}.toml" sha256 "${RUST_MANIFEST_SHA256}" rust-manifest.toml
	RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo ./rustup-init -y --no-modify-path \
		--profile minimal --default-toolchain "${RUST_VERSION}" --component clippy,rustfmt
	toolchain="${RUST_VERSION}-${TRIPLE}-unknown-linux-gnu"
	check_rust_manifest rust-manifest.toml "${RUST_MANIFEST_SHA256}" \
		"/opt/rustup/toolchains/${toolchain}/lib/rustlib/multirust-channel-manifest.toml" \
		"/opt/rustup/update-hashes/${toolchain}"
	normalize_rust_components "/opt/rustup/toolchains/${toolchain}/lib/rustlib/components"
	rm -rf /opt/rustup/toolchains/*/share/doc
	chmod -R a+rX /opt/rustup /opt/cargo
	;;
yq)
	sh $F "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${TARGETARCH}" sha256 "$(pin YQ_SHA256)" yq
	install -m 0755 yq /usr/local/bin/yq
	;;
gh)
	sh $F "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz" sha256 "$(pin GH_SHA256)" gh.tgz
	tar -xzf gh.tgz
	install -m 0755 "gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh
	;;
uv)
	sh $F "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TRIPLE}-unknown-linux-gnu.tar.gz" sha256 "$(pin UV_SHA256)" uv.tgz
	tar -xzf uv.tgz
	install -m 0755 "uv-${TRIPLE}-unknown-linux-gnu/uv" "uv-${TRIPLE}-unknown-linux-gnu/uvx" /usr/local/bin/
	;;
ruff)
	# https://github.com/astral-sh/ruff/releases
	sh $F "https://github.com/astral-sh/ruff/releases/download/${RUFF_VERSION}/ruff-${TRIPLE}-unknown-linux-gnu.tar.gz" sha256 "$(pin RUFF_SHA256)" ruff.tgz
	tar -xzf ruff.tgz
	install -m 0755 "ruff-${TRIPLE}-unknown-linux-gnu/ruff" /usr/local/bin/ruff
	;;
trivy)
	sh $F "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" sha256 "$(pin TRIVY_SHA256)" trivy.tgz
	tar -xzf trivy.tgz trivy
	install -m 0755 trivy /usr/local/bin/trivy
	;;
abtop)
	# Official release archives: https://github.com/graykode/abtop/releases
	sh $F "https://github.com/graykode/abtop/releases/download/v${ABTOP_VERSION}/abtop-${TRIPLE}-unknown-linux-gnu.tar.xz" sha256 "$(pin ABTOP_SHA256)" abtop.tar.xz
	tar -xJf abtop.tar.xz "abtop-${TRIPLE}-unknown-linux-gnu/abtop"
	install -m 0755 "abtop-${TRIPLE}-unknown-linux-gnu/abtop" /usr/local/bin/abtop
	;;
golangci-lint)
	G="golangci-lint-${GOLANGCI_LINT_VERSION}-linux-${TARGETARCH}"
	sh $F "https://github.com/golangci/golangci-lint/releases/download/v${GOLANGCI_LINT_VERSION}/${G}.tar.gz" sha256 "$(pin GOLANGCI_LINT_SHA256)" golangci.tgz
	tar -xzf golangci.tgz
	install -m 0755 "${G}/golangci-lint" /usr/local/bin/golangci-lint
	;;
tea)
	# Gitea CLI, from gitea.com
	sh $F "https://gitea.com/gitea/tea/releases/download/v${TEA_VERSION}/tea-${TEA_VERSION}-linux-${TARGETARCH}.xz" sha256 "$(pin TEA_SHA256)" tea.xz
	xz -d tea.xz
	install -m 0755 tea /usr/local/bin/tea
	;;
kubectl)
	# https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
	sh $F "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" sha256 "$(pin KUBECTL_SHA256)" kubectl
	install -m 0755 kubectl /usr/local/bin/kubectl
	;;
helm)
	# https://helm.sh/docs/intro/install/#from-the-binary-releases
	sh $F "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" sha256 "$(pin HELM_SHA256)" helm.tgz
	tar -xzf helm.tgz "linux-${TARGETARCH}/helm"
	install -m 0755 "linux-${TARGETARCH}/helm" /usr/local/bin/helm
	;;
claude)
	# The native Claude Code binary from Anthropic's release host, the file the native
	# installer downloads (https://claude.ai/install.sh). The pinned SHA-256 comes from
	# the release's GPG-signed manifest.json (code.claude.com/docs/en/setup, "Binary
	# integrity and code signing").
	sh $F "https://downloads.claude.ai/claude-code-releases/${CLAUDE_CODE_VERSION}/${CLAUDE_PLATFORM}/claude" sha256 "$(pin CLAUDE_CODE_SHA256)" claude
	install -m 0755 claude /usr/local/bin/claude
	/usr/local/bin/claude --version >/dev/null
	;;
codex)
	# The complete release package, laid out as OpenAI's installer does
	# (chatgpt.com/codex/install.sh, install_package_release). The interactive CLI needs it.
	sh $F "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-package-${TRIPLE}-unknown-linux-musl.tar.gz" sha256 "$(pin CODEX_SHA256)" codex.tgz
	mkdir -p /opt/codex
	# As root, tar would keep the archive's owner; the install must be root-owned.
	tar --no-same-owner -xzf codex.tgz -C /opt/codex
	chown -R root:root /opt/codex
	test -f /opt/codex/codex-package.json
	chmod 0755 /opt/codex/bin/codex /opt/codex/bin/codex-code-mode-host /opt/codex/codex-path/rg
	if [ -f /opt/codex/codex-resources/bwrap ]; then chmod 0755 /opt/codex/codex-resources/bwrap; fi
	# The voice host (77 MB) captures audio for dictation; a container has no microphone.
	rm -rf /opt/codex/codex-resources/voice
	ln -sf bin/codex /opt/codex/codex
	# Codex writes state under $HOME when it runs. This stage's /root is not copied
	# into the image.
	/opt/codex/bin/codex --version >/dev/null
	;;
node)
	# The official Linux binary tarball from nodejs.org, with npm and npx inside.
	sh $F "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" sha256 "$(pin NODE_SHA256)" node.txz
	mkdir -p /opt/node
	# As root, tar would keep the archive's owner (uid 1001 for this tarball); the install
	# must be root-owned.
	tar --no-same-owner --strip-components=1 -xJf node.txz -C /opt/node
	# Headers and docs are not needed to run node; keep LICENSE.
	rm -rf /opt/node/include /opt/node/share /opt/node/README.md /opt/node/CHANGELOG.md
	chown -R root:root /opt/node
	/opt/node/bin/node --version >/dev/null
	;;
agy)
	# The tarball named in versions.env; the binary inside is "antigravity" (install.sh).
	sh $F "$(pin AGY_URL)" sha512 "$(pin AGY_SHA512)" agy.tgz
	if tar -tzf agy.tgz >/dev/null 2>&1; then
		tar -xzf agy.tgz antigravity
		install -m 0755 antigravity /usr/local/bin/agy
	else
		# The official install.sh also accepts a raw binary payload.
		install -m 0755 agy.tgz /usr/local/bin/agy
	fi
	;;
opencode)
	# OpenCode v2: the npm platform package, checked against the registry's integrity.
	sh $F "https://registry.npmjs.org/@opencode/cli-${OC}/-/cli-${OC}-${OPENCODE_VERSION}.tgz" sri "$(pin OPENCODE_INTEGRITY)" opencode.tgz
	tar -xzf opencode.tgz package/bin/opencode
	install -m 0755 package/bin/opencode /usr/local/bin/opencode
	;;
normalize-rust-components)
	shift
	normalize_rust_components "$@"
	;;
check-rust-manifest)
	# Runs the check alone, for tests: install-tool.sh check-rust-manifest PINNED SHA256 USED UPDATE_HASH
	shift
	check_rust_manifest "$@"
	;;
*)
	echo "install-tool.sh: unknown tool $1" >&2
	exit 2
	;;
esac
cd /
rm -rf "$W"
