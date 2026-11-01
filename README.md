# Agentainer

Agentainer is one container image with four AI coding agents and a shared set of developer tools. You run it in a terminal on a laptop, a server or a Kubernetes cluster.

- Agents: [Claude Code](https://code.claude.com/docs/en/setup), [Codex CLI](https://github.com/openai/codex), [Antigravity CLI](https://antigravity.google/docs/overview?tab=cli) (`agy`) and [OpenCode v2](https://opencode.ai/v2/docs).
- Base: Ubuntu 26.04 LTS, pinned by digest, with apt packages from the [Ubuntu snapshot service](https://documentation.ubuntu.com/server/how-to/software/snapshot-service/) at a pinned date.
- Tools: git, gh, Go, Rust, Python with uv and pipx, Node.js, GCC/G++, CMake, Ninja, pkg-config, psql, kubectl, Helm, AWS CLI v2, abtop, ripgrep, jq, yq, shellcheck, trivy and more. `/etc/agentainer/versions.json` in the image lists every version.
- Platforms: `linux/amd64` and `linux/arm64`. On amd64 the agents also start on CPUs without AVX2; CI checks this on every build.

Agents can modify mounted files, use supplied credentials and reach network services. See the [security limits](docs/security.md).

These docs describe the current source. Features merged after the newest release tag are only in a local build until the next release ([release policy](docs/versions.md#releases)).

## Contents

- [Quick start](#quick-start)
- [Documentation](#documentation)
- [License](#license)

## Quick start

You need Podman or Docker. The launcher [`bin/agentainer`](bin/agentainer) is a POSIX shell script.

Set `AGENTAINER_IMAGE` to a published version tag; no `latest` tag exists before the first stable release ([release versions](docs/versions.md#releases)). Or build locally with `scripts/build.sh` (`RUNTIME=docker sh scripts/build.sh` on a Docker host) and use `localhost/agentainer:dev`.

```sh
mkdir -p ~/.config/agentainer
cp env.example ~/.config/agentainer/env
chmod 600 ~/.config/agentainer/env      # then fill in the keys you use
export AGENTAINER_IMAGE=ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261024.1
bin/agentainer up ~/code                 # ~/code becomes /workspace
bin/agentainer attach                    # tmux session "main"
```

Start an agent in a tmux window (`claude`, `codex`, `agy` or `opencode`). Close the terminal whenever you like. `bin/agentainer attach` brings you back to the same session with the agents still running.

## Documentation

The [documentation index](docs/README.md) lists the same pages.

| Topic | Read |
|---|---|
| Launcher commands, `docker run` and `podman run`, sudo, file ownership, upgrading | [docs/running.md](docs/running.md) |
| Signing in to each agent, which Claude login wins, GitHub tokens | [docs/logins.md](docs/logins.md) |
| Where each agent keeps settings, instructions and skills, status lines, MCP logins | [docs/agents.md](docs/agents.md) |
| Seeded shell, Git, tmux, Vim, EditorConfig, agent settings and Ayu-inspired Agentainer colors | [docs/defaults.md](docs/defaults.md) |
| Your own configs, bind-mounted homes, separate test homes and custom images | [docs/customization.md](docs/customization.md) |
| The shared `AGENTS.md`, MCP servers, tools that agents install, OpenRouter | [docs/configuration.md](docs/configuration.md) |
| Python tests and linting, JavaScript tooling, native builds and PostgreSQL scripts | [docs/project-tools.md](docs/project-tools.md) |
| Optional Playwright setup, persistent browser downloads and execution checks | [docs/browser-testing.md](docs/browser-testing.md) |
| Optional Go, Rust, Python and TypeScript language servers | [docs/language-tooling.md](docs/language-tooling.md) |
| Optional agent plugins, token/context tools and documentation lookup | [docs/plugins.md](docs/plugins.md) |
| Agent session monitoring with abtop | [docs/monitoring.md](docs/monitoring.md) |
| Kubernetes with ContainerSSH | [docs/kubernetes.md](docs/kubernetes.md) |
| The Kelos variant image | [docs/kelos.md](docs/kelos.md) |
| What the container isolates, agent permissions, vulnerability reports | [docs/security.md](docs/security.md) |
| Pinned versions, scheduled updates, releases and signatures | [docs/versions.md](docs/versions.md) |
| Offline diagnostics with `agentainer doctor`, error messages and fixes | [docs/troubleshooting.md](docs/troubleshooting.md) |

To report a vulnerability, follow [SECURITY.md](SECURITY.md). To contribute, read [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). The image also contains software under other licenses.
