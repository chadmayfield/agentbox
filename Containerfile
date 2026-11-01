# check=skip=InvalidDefaultArgInFrom
# Agentainer image. Build with scripts/build.sh, which passes every pin in versions.env
# as a build argument. BASE_IMAGE has no default because its digest lives only in
# versions.env; the check directive above silences BuildKit's warning about that
# (docs.docker.com/build/checks).
#
# Each tool is installed in its own stage that declares only that tool's pins, and the
# final stage copies the result. A pin change rebuilds one stage. When the builder
# clamps file times to SOURCE_DATE_EPOCH (BuildKit rewrite-timestamp, Podman 5.6 or
# later) and the same builder version compresses the layers, an unchanged tool produces
# a byte-identical layer, so users do not download it again.
ARG BASE_IMAGE

# The base image has no CA bundle and snapshot.ubuntu.com is https. Only the bundle
# leaves this stage; every package in the final image comes from the snapshot.
FROM ${BASE_IMAGE} AS certs
RUN apt-get update \
	&& DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates

# Download tools for the tool stages. Every file they download is checked against a
# pin, so the versions of these build-only packages do not reach the image.
FROM ${BASE_IMAGE} AS fetch
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN apt-get update \
	&& DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
		ca-certificates curl xz-utils python3-minimal \
	&& rm -rf /var/lib/apt/lists/*
COPY build/fetch.sh build/install-tool.sh /usr/local/lib/agentainer-build/

FROM fetch AS go
ARG TARGETARCH
ARG GO_VERSION
ARG GO_SHA256_AMD64
ARG GO_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh go

FROM fetch AS rust
ARG TARGETARCH
ARG RUSTUP_VERSION
ARG RUSTUP_SHA256_AMD64
ARG RUSTUP_SHA256_ARM64
ARG RUST_VERSION
ARG RUST_MANIFEST_SHA256
RUN bash /usr/local/lib/agentainer-build/install-tool.sh rust

FROM fetch AS yq
ARG TARGETARCH
ARG YQ_VERSION
ARG YQ_SHA256_AMD64
ARG YQ_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh yq

FROM fetch AS gh
ARG TARGETARCH
ARG GH_VERSION
ARG GH_SHA256_AMD64
ARG GH_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh gh

FROM fetch AS uv
ARG TARGETARCH
ARG UV_VERSION
ARG UV_SHA256_AMD64
ARG UV_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh uv

FROM fetch AS trivy
ARG TARGETARCH
ARG TRIVY_VERSION
ARG TRIVY_SHA256_AMD64
ARG TRIVY_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh trivy

FROM fetch AS ruff
ARG TARGETARCH
ARG RUFF_VERSION
ARG RUFF_SHA256_AMD64
ARG RUFF_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh ruff

FROM fetch AS abtop
ARG TARGETARCH
ARG ABTOP_VERSION
ARG ABTOP_SHA256_AMD64
ARG ABTOP_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh abtop

FROM fetch AS golangci-lint
ARG TARGETARCH
ARG GOLANGCI_LINT_VERSION
ARG GOLANGCI_LINT_SHA256_AMD64
ARG GOLANGCI_LINT_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh golangci-lint

FROM fetch AS tea
ARG TARGETARCH
ARG TEA_VERSION
ARG TEA_SHA256_AMD64
ARG TEA_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh tea

FROM fetch AS kubectl
ARG TARGETARCH
ARG KUBECTL_VERSION
ARG KUBECTL_SHA256_AMD64
ARG KUBECTL_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh kubectl

FROM fetch AS helm
ARG TARGETARCH
ARG HELM_VERSION
ARG HELM_SHA256_AMD64
ARG HELM_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh helm

FROM fetch AS awscli
ARG TARGETARCH
ARG AWSCLI_VERSION
ARG AWSCLI_SHA256_AMD64
ARG AWSCLI_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh awscli

FROM fetch AS claude
ARG TARGETARCH
ARG CLAUDE_CODE_VERSION
ARG CLAUDE_CODE_SHA256_AMD64
ARG CLAUDE_CODE_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh claude

FROM fetch AS codex
ARG TARGETARCH
ARG CODEX_VERSION
ARG CODEX_SHA256_AMD64
ARG CODEX_SHA256_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh codex

FROM fetch AS node
ARG TARGETARCH
ARG NODE_VERSION
ARG NODE_SHA256_AMD64
ARG NODE_SHA256_ARM64
# node links libatomic.so.1, which the final image gets from apt-packages.txt. This install
# comes from the live archive only for the node --version check in this stage and is not
# copied into the image.
RUN apt-get update \
	&& DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libatomic1 \
	&& rm -rf /var/lib/apt/lists/*
RUN bash /usr/local/lib/agentainer-build/install-tool.sh node

FROM fetch AS agy
ARG TARGETARCH
ARG AGY_URL_AMD64
ARG AGY_URL_ARM64
ARG AGY_SHA512_AMD64
ARG AGY_SHA512_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh agy

FROM fetch AS opencode
ARG TARGETARCH
ARG OPENCODE_VERSION
ARG OPENCODE_INTEGRITY_AMD64
ARG OPENCODE_INTEGRITY_ARM64
RUN bash /usr/local/lib/agentainer-build/install-tool.sh opencode

FROM fetch AS unslop
ARG UNSLOP_COMMIT
ARG UNSLOP_SHA256
ARG UNSLOP_LICENSE_SHA256
COPY build/install-unslop.sh /usr/local/lib/agentainer-build/install-unslop.sh
RUN sh /usr/local/lib/agentainer-build/install-unslop.sh

FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG AGENT_UID=1000
ARG AGENT_GID=1000
# Podman honours SHELL only with --format docker, which scripts/build.sh passes.
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# Stops the build unless RUN steps use bash with errexit and pipefail.
RUN [ -n "${BASH_VERSION:-}" ] && [[ $- == *e* ]] && set -o | grep -Eq '^pipefail[[:space:]]+on' \
	&& mkdir -p /usr/local/share/agentainer \
	&& echo "bash ${BASH_VERSION} errexit pipefail" > /usr/local/share/agentainer/build-shell.txt

COPY build/apt-packages.txt build/check-apt-snapshot.py /tmp/agentainer-build/

# apt packages from the pinned Ubuntu snapshot.
# - Both architectures use archive.ubuntu.com: the arm64 image defaults to
#   ports.ubuntu.com, which the snapshot service does not cover, while
#   archive.ubuntu.com serves resolute arm64 and has snapshots.
# - A "Snapshot: <ID>" field in each source (apt sources.list(5)) pins apt.
# - upgrade brings the base image's own packages to their snapshot versions.
#   Always-Include-Phased-Updates makes upgrades take the same (newest) versions
#   that fresh installs already get, instead of deferring phased ones
#   (apt_preferences(5), "Phased Updates").
# - check-apt-snapshot.py fails the build if any installed version is not in the snapshot.
# - Failed indexes and archives get five retries. update fails if any index is
#   unavailable, so installation cannot continue with missing package lists
#   (apt-get(8), --error-on=any; apt.conf(5), Acquire::Retries).
# - The apt and dpkg logs hold build times and are removed.
ARG APT_SNAPSHOT
# The bootstrap bundle is available only during this RUN, outside final image layers.
# https://docs.docker.com/reference/dockerfile/#run---mounttypebind
RUN --mount=type=bind,from=certs,source=/etc/ssl/certs/ca-certificates.crt,target=/tmp/agentainer-build/ca.crt \
    test -n "${APT_SNAPSHOT}" \
	&& export DEBIAN_FRONTEND=noninteractive \
	&& printf 'Types: deb\nURIs: http://archive.ubuntu.com/ubuntu/\nSuites: resolute resolute-updates resolute-backports\nComponents: main universe restricted multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nSnapshot: %s\n\nTypes: deb\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: resolute-security\nComponents: main universe restricted multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nSnapshot: %s\n' "${APT_SNAPSHOT}" "${APT_SNAPSHOT}" > /etc/apt/sources.list.d/ubuntu.sources \
	&& APT="apt-get -o Acquire::Retries=5 -o Acquire::https::CAInfo=/tmp/agentainer-build/ca.crt -o APT::Get::Always-Include-Phased-Updates=true" \
	&& $APT update --error-on=any \
	&& $APT upgrade -y \
	&& xargs -a /tmp/agentainer-build/apt-packages.txt $APT install -y --no-install-recommends \
	&& apt-cache policy bash > /usr/local/share/agentainer/apt-policy.txt \
	&& python3 /tmp/agentainer-build/check-apt-snapshot.py /usr/local/share/agentainer/apt-unpinned.txt \
	&& sed -i '/^Snapshot: /d' /etc/apt/sources.list.d/ubuntu.sources \
	&& rm -rf /var/lib/apt/lists/* \
	&& rm -f /var/log/dpkg.log /var/log/alternatives.log /var/log/apt/history.log /var/log/apt/term.log

# Debian names these binaries fdfind and batcat (their package file lists).
# ping ships with the cap_net_raw file capability, which fails under runtimes that
# drop NET_RAW (Podman's default, the Kubernetes example). Without it, ping uses an
# unprivileged ICMP socket, allowed by the net.ipv4.ping_group_range sysctl that the
# launcher and the pod spec set.
# The ubuntu:26.04 base image ships Canonical's Pebble service manager in
# /usr/bin/pebble, owned by no package. Nothing here uses it, and its Go runtime
# adds scanner findings.
RUN ln -s /usr/bin/fdfind /usr/local/bin/fd \
	&& ln -s /usr/bin/batcat /usr/local/bin/bat \
	&& python3 -c 'import os; os.removexattr("/usr/bin/ping", "security.capability")' \
	&& rm -rf /usr/bin/pebble /var/lib/pebble

# Renames the base image's ubuntu user (UID 1000) to agent. With other IDs, reuses a
# group that already has the GID (for example 20, which is "dialout" in Ubuntu and
# "staff" on macOS).
RUN if [ "${AGENT_UID}" = 1000 ] && [ "${AGENT_GID}" = 1000 ]; then \
		groupmod -n agent ubuntu \
		&& usermod -l agent -d /home/agent -m -c Agentainer -G "" ubuntu; \
	else \
		userdel -r ubuntu 2>/dev/null || true; \
		getent group "${AGENT_GID}" >/dev/null || groupadd -g "${AGENT_GID}" agent; \
		useradd -m -u "${AGENT_UID}" -g "${AGENT_GID}" -s /bin/bash -c Agentainer agent; \
	fi \
	&& printf 'agent ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/agent \
	&& chmod 0440 /etc/sudoers.d/agent \
	&& install -d -o agent -g "${AGENT_GID}" /workspace

ENV LANG=C.UTF-8

COPY --from=go /usr/local/go /usr/local/go
COPY --from=rust /opt/rustup /opt/rustup
COPY --from=rust /opt/cargo /opt/cargo
COPY --from=yq /usr/local/bin/yq /usr/local/bin/yq
COPY --from=gh /usr/local/bin/gh /usr/local/bin/gh
COPY --from=uv /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --from=ruff /usr/local/bin/ruff /usr/local/bin/ruff
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=abtop /usr/local/bin/abtop /usr/local/bin/abtop
COPY --from=golangci-lint /usr/local/bin/golangci-lint /usr/local/bin/golangci-lint
COPY --from=tea /usr/local/bin/tea /usr/local/bin/tea
COPY --from=kubectl /usr/local/bin/kubectl /usr/local/bin/kubectl
COPY --from=helm /usr/local/bin/helm /usr/local/bin/helm
COPY --from=awscli /usr/local/aws-cli /usr/local/aws-cli
COPY --from=claude /usr/local/bin/claude /usr/local/bin/claude
COPY --from=codex /opt/codex /opt/codex
COPY --from=node /opt/node /opt/node
COPY --from=agy /usr/local/bin/agy /usr/local/bin/agy
COPY --from=opencode /usr/local/bin/opencode /usr/local/bin/opencode
COPY --from=unslop /usr/local/share/agentainer/skills/unslop /usr/local/share/agentainer/skills/unslop

ENV RUSTUP_HOME=/opt/rustup \
	GOTOOLCHAIN=local \
	PATH=/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

COPY versions.env /usr/local/share/agentainer/versions.env
COPY build/write-versions-json.py /tmp/agentainer-build/
# COPY keeps each file's mode from the build context, so a build host with umask 077
# would make /etc 0700 and the seed files 0600. rootfs is staged first and every path
# in it gets a fixed mode before it is copied to /: directories 0755, commands in
# usr/local/bin 0755, other files 0644. The entrypoint sources its steps, so they do
# not need the execute bit. Paths that rootfs does not contain keep their modes.
COPY rootfs/ /tmp/agentainer-build/rootfs/
RUN cd /tmp/agentainer-build/rootfs \
	&& find . -type d -exec chmod 0755 {} + \
	&& find . -type f -exec chmod 0644 {} + \
	&& find usr/local/bin -type f -exec chmod 0755 {} + \
	&& find . -mindepth 1 -maxdepth 1 -exec cp -a {} / \; \
	&& cd / \
	&& rm -rf /tmp/agentainer-build/rootfs \
	&& ln -s /opt/codex/bin/codex /usr/local/bin/codex \
	&& ln -s /opt/node/bin/node /usr/local/bin/node \
	&& ln -s /opt/node/bin/npm /usr/local/bin/npm \
	&& ln -s /opt/node/bin/npx /usr/local/bin/npx \
	&& ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws \
	&& ln -s /usr/local/aws-cli/v2/current/bin/aws_completer /usr/local/bin/aws_completer \
	&& test -x /usr/local/bin/codex \
	&& /usr/local/bin/aws --version >/dev/null \
	&& test -x /usr/local/bin/node \
	&& /usr/local/bin/node --version >/dev/null \
	&& test -x /usr/local/bin/agentainer-entrypoint \
	&& python3 /tmp/agentainer-build/write-versions-json.py

ARG IMAGE_VERSION=dev
ENV AGENTAINER_IMAGE_VERSION="${IMAGE_VERSION}"
ARG VCS_REF=unknown
ARG BUILD_DATE
LABEL org.opencontainers.image.version="${IMAGE_VERSION}" \
	org.opencontainers.image.revision="${VCS_REF}" \
	org.opencontainers.image.created="${BUILD_DATE}" \
	org.opencontainers.image.title="Agentainer" \
	org.opencontainers.image.description="Claude Code, Codex, Antigravity CLI and OpenCode in one container" \
	org.opencontainers.image.source="https://github.com/chadmayfield/agentainer" \
	org.opencontainers.image.base.name="${BASE_IMAGE}" \
	io.github.chadmayfield.agentainer.versions="/etc/agentainer/versions.json"

ENV DISABLE_UPDATES=1 \
	AGY_CLI_DISABLE_AUTO_UPDATE=true \
	OPENCODE_DISABLE_AUTOUPDATE=1 \
	NPM_CONFIG_UPDATE_NOTIFIER=false \
	CLAUDE_CODE_NONBLOCKING_STDOUT=1 \
	CLAUDE_CODE_TMUX_TRUECOLOR=1

# Named volumes copy the image's /home/agent on first use, so it carries the same
# shell defaults the entrypoint seeds into an empty PVC.
RUN install -m 0644 -o agent -g "${AGENT_GID}" /etc/agentainer/home/.profile /home/agent/.profile \
	&& install -m 0644 -o agent -g "${AGENT_GID}" /etc/agentainer/home/.bashrc /home/agent/.bashrc \
	&& rm -rf /tmp/agentainer-build \
	&& install -d -o agent -g "${AGENT_GID}" /var/lib/agentainer /var/lib/agentainer/tools \
	&& install -d /etc/agentainer/home /etc/agentainer/seed

# Tools that agents install go under /var/lib/agentainer/active, a per-container symlink
# that the entrypoint points at the ephemeral or persistent root. These are static ENV
# values because exec sessions do not inherit variables that PID 1 exports.
ENV AGENTAINER_TOOLS=ephemeral \
	NPM_CONFIG_PREFIX=/var/lib/agentainer/active/npm \
	CARGO_HOME=/var/lib/agentainer/active/cargo \
	CARGO_INSTALL_ROOT=/var/lib/agentainer/active \
	GOPATH=/var/lib/agentainer/active/go \
	GOBIN=/var/lib/agentainer/active/bin \
	UV_TOOL_DIR=/var/lib/agentainer/active/uv \
	UV_TOOL_BIN_DIR=/var/lib/agentainer/active/bin \
	PIPX_HOME=/var/lib/agentainer/active/pipx \
	PIPX_BIN_DIR=/var/lib/agentainer/active/bin \
	PYTHONUSERBASE=/var/lib/agentainer/active/python \
	PATH=/usr/local/go/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/var/lib/agentainer/active/bin:/var/lib/agentainer/active/npm/bin:/var/lib/agentainer/active/python/bin

USER agent
WORKDIR /workspace
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
	CMD ["/usr/local/bin/agentainer-healthcheck"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agentainer-entrypoint"]
CMD ["sleep", "infinity"]
