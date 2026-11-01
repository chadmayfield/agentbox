# Security

This page covers what the container isolates, agent permissions and vulnerability reports. To report a vulnerability in Agentainer itself, follow [SECURITY.md](../SECURITY.md).

## Contents

- [What the container isolates](#what-the-container-isolates)
  - [Credentials and runtime settings](#credentials-and-runtime-settings)
- [Agent permissions](#agent-permissions)
- [Vulnerability reports](#vulnerability-reports)

## What the container isolates

The container restricts direct filesystem and process access through its mounts and namespaces. Writable mounts, shared home files and reachable host services can let container code affect the host.

It does not isolate:

- The code you mount. Agents can change or delete it.
- Host execution of mounted files. Git configuration and hooks, generated executables, editor tasks and project scripts can run as your host user after an agent changes them. Review these files before running host commands, or use a separate host clone. Disabling Git hooks alone does not disable every execution path ([Git configuration](https://git-scm.com/docs/git-config)).
- Host network services. Whether container code can reach a service bound to host loopback depends on the runtime's networking; Podman, for example, provides `host.containers.internal` ([Podman networking](https://docs.podman.io/en/latest/markdown/podman-run.1.html)). Authenticate sensitive host services, and use an offline network when network access is unnecessary.
- Shared home volumes. Every container using the same home trusts its shell startup files, agent settings and installed tools. Use different homes for different trust levels. Enabling sudo in a later container also grants its startup code access to container root.
- Forwarded SSH agents. Processes with access to the socket can request signatures with its loaded keys. Use a dedicated agent with only the required keys. Keys with confirmation constraints can require host approval ([ssh-add](https://man.openbsd.org/ssh-add)).
- Terminal output. Shells and attached panes send output to your host terminal. Arbitrary tmux passthrough is disabled by default. Enabling `allow-passthrough` in your own tmux configuration permits wrapped escape sequences to reach the outer terminal, including clipboard requests on terminals that accept them ([tmux manual](https://man.openbsd.org/tmux)).
- Outbound network access, unless you use the NetworkPolicy in Kubernetes ([docs/kubernetes.md](kubernetes.md#network-policy)).
- Credentials. See [credentials and runtime settings](#credentials-and-runtime-settings).
- The host kernel. This is a container, not a VM.
- Everything inside the container once sudo is on ([sudo](running.md#sudo)).

The image runs as the non-root user `agent` (UID 1000), and agent binaries are root-owned. With sudo off, agents cannot replace them. A raw image run has passwordless sudo unless the runtime sets `no-new-privileges`. The launcher sets it by default, and the Kubernetes example disables privilege escalation. Add the option to raw runs too ([sudo](running.md#sudo)).

### Credentials and runtime settings

- **Every variable in the env file or Secret is readable by every process in the container**: all four agents, the tools they run, and MCP servers. Pass only the keys you need, and prefer narrowly scoped tokens.
- Env-file values stay in the engine's stored container configuration. Users with engine access can read them with `inspect`; on rootful Docker that includes members of the Docker group ([Podman inspect](https://docs.podman.io/en/latest/markdown/podman-inspect.1.html), [Docker env files](https://docs.docker.com/reference/cli/docker/container/run/#env)).
- Changing the env file does not update an existing container, and stop and start do not refresh it. Recreate the container with `agentainer update` or `down` and `up`, and inspect leftover update backups before you remove them.
- Agent update variables and `GOTOOLCHAIN=local` are defaults that container code can override. Root ownership is what stops ordinary replacement of image tools; sudo removes that protection. Go details are in [language tooling](language-tooling.md#go-with-gopls) ([Go toolchains](https://go.dev/doc/toolchain)).

## Agent permissions

Agents keep their own approval prompts; the image turns on no skip-permissions mode. If you turn one on, note Anthropic's warning: "When executed with `--dangerously-skip-permissions`, dev containers do not prevent a malicious project from exfiltrating anything accessible inside the container, including the Claude Code credentials" ([devcontainer docs](https://code.claude.com/docs/en/devcontainer)).

Codex's own sandbox is off: the seeded `~/.codex/config.toml` sets `sandbox_mode = "danger-full-access"`, so the container provides the isolation. The file's comment gives the reason: Codex's bubblewrap sandbox cannot start inside a container ("bwrap: Can't mount devpts on /newroot/dev/pts: Permission denied"). Whether it starts under every runtime configuration is not verified. The seeded `approval_policy = "on-request"` lets Codex ask for approval; it does not require confirmation for every command. Codex can run commands against mounted files and use available network access without prompting. Treat every writable mount and supplied credential as accessible to it ([OpenAI approval semantics](https://learn.chatgpt.com/docs/agent-approvals-security)).

Antigravity's terms say: "Wrapping `agy` inside third-party coding agents or applications ... is not supported under consumer plans" ([Antigravity FAQ](https://antigravity.google/docs/faq.md)). Agentainer installs `agy` for you to run yourself and does not wrap it.

Gemini CLI is not included. Google wrote: "On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge using Gemini Code Assist for individuals" ([Google Developers Blog](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)). Antigravity CLI is Google's named replacement.

## Vulnerability reports

CI scans candidate images and the exact pushed release digests with an independent Trivy container pinned by digest in `versions.env`. It does not execute the scanner bundled in the image under test or load a secret-rule override from the checkout. A secret fails the build or stops release promotion. Vulnerabilities are reported and do not fail it ([workflow](../.github/workflows/build.yml), [Trivy image scans](https://trivy.dev/docs/latest/target/container_image/)).

- Pull requests and `develop`: the run's summary page shows counts by severity, how many have a fix, and up to 50 critical findings. The full trivy JSON is the `vulnerabilities-<arch>` artifact on that run.
- Releases: the scan runs on the images pushed to GHCR. The release notes start with the same summary, and `vulnerabilities-amd64.json` and `vulnerabilities-arm64.json` are attached to the release.
- Kernel CVEs filed against `linux-libc-dev`, the kernel header package that C compilers need, are counted separately: the container runs on the host's kernel.

Many findings sit in upstream binaries that this repo installs as released. They are fixed by upstream releases, which reach the image through the scheduled version update ([docs/versions.md](versions.md)). [AGENTS.md](../AGENTS.md#vulnerabilities-in-bundled-tools) describes how a tool that stops shipping fixes is handled.
