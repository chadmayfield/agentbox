# Troubleshooting

This page covers `agentainer doctor` and common error messages with their fixes.

## Contents

- [Offline diagnostics](#offline-diagnostics)
- [Common problems](#common-problems)

## Offline diagnostics

From the host, check the running container with:

```sh
bin/agentainer doctor
bin/agentainer doctor agentainer-test --json
```

N defaults to `agentainer`. Inside the container, run `agentainer-doctor` or `agentainer-doctor --json`. The image must include that command; updating only the host launcher does not add it to an older image.

The command reports `ok`, `warn` or `fail` for:

- The image's `/etc/agentainer/versions.json` inventory format.
- Home-directory read, write and search access, plus group/other write permissions.
- The tools mode, active symlink target and tool-root write access.
- Syntax of the five seeded agent settings files listed in [default configuration](defaults.md#agent-configurations).
- Shared MCP input validation, ownership metadata, interrupted writes and the last successful input-hash stamp. An active sync produces a warning instead of reading partially updated state.
- Version-command execution for the four agents and the core tools listed in [`agentainer-doctor`](../rootfs/usr/local/bin/agentainer-doctor).

Settings checks respect `CLAUDE_CONFIG_DIR` ([Claude settings](https://code.claude.com/docs/en/settings#find-or-create-your-settings-files)), `CODEX_HOME` ([Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)) and `XDG_CONFIG_HOME` for OpenCode (`opencode debug paths` shows the resolved paths). Missing settings files and OpenCode JSONC files produce warnings; invalid JSON or TOML and unreadable files fail. The check covers home settings syntax, not the precedence of project, profile and managed settings.

Version probes run in a temporary directory with a temporary home, without credentials, with a five-second timeout each. The report prints no configuration values, provider URLs, tool output or exception details. The command does not rewrite settings, install tools, repair MCP state or make model requests.

Exit status is `0` when no check failed, `1` when any check failed, and `2` for invalid arguments. Warnings do not fail the command. JSON output contains an overall `status` and a `checks` array; each check has `name`, `status` and `message` fields.

Not checked: login validity, agent-specific setting semantics, model access, MCP server connectivity and live approval behavior. MCP status records the last successful sync input, not whether every server is available. When the syntax checks pass but an agent still rejects a setting, use that agent's own diagnostics ([setting up the agents](agents.md#check-the-setup)).

## Common problems

**The container reports `starting` or `unhealthy`.**
Inspect `.State.Health` as described in [container health](running.md#container-health). A new container can stay `starting` while its entrypoint runs. Failures report `startup incomplete`, `home permissions` or `tools directory unavailable`, without printing environment values. Check the container's startup logs and home mount permissions, then run `agentainer doctor`. A repaired container becomes `healthy` on its next successful probe. The probe does not test agent authentication or network access.

**Podman shows `starting` with no probe log.**
An older image without a health check can show `starting` on Podman 5.3.2 with an empty `.Config.Healthcheck` object. That empty object is not a running check. Podman sets `starting` whenever a non-null health-check object exists ([Podman source](https://github.com/containers/podman/blob/v5.3.2/libpod/container_internal.go#L1291-L1300)). Podman 5.3.2 also keeps suppressing failure counts until the start period ends, while Docker ends it after the first successful probe ([Podman source](https://github.com/containers/podman/blob/v5.3.2/libpod/healthcheck.go#L127-L136)).

**A Podman container has no health check although the image defines one.**
Add `--health-cmd=/usr/local/bin/agentainer-healthcheck` and the other options from [container health](running.md#container-health) to a raw `podman run`, only with an image that includes the probe. The launcher does not add them ([Podman health command option](https://docs.podman.io/en/v5.3.2/markdown/podman-run.1.html#health-cmd-command)).

**`sudo: The "no new privileges" flag is set, which prevents sudo from running as root.`**
sudo is off by default. Remove the container with `bin/agentainer down` (the home stays), then run `bin/agentainer up --sudo` with the same DIR. For a raw `docker run` or `podman run`, leave out `--security-opt no-new-privileges=true` ([sudo](running.md#sudo)).

**`ping: socket: Operation not permitted`**
The container was started without `--sysctl "net.ipv4.ping_group_range=1000 1000"`. The launcher and the Kubernetes example set it; add it to raw `run` commands.

**The container name `agentainer` is already in use**
A container with that name exists. If it is running, `bin/agentainer attach` connects to it. If it is stopped, `bin/agentainer start` starts it, and `bin/agentainer down` removes it. The home volume stays either way.

**`agentainer: ... has no option labels` when running `agentainer update`**
`update` needs the option labels that `agentainer up` records, so it cannot recreate this container. The fix depends on the container's labels:

- It has the Agentainer label but no option labels, for example from an older launcher: run `bin/agentainer down`, then `bin/agentainer up` with the options you want.
- It has no Agentainer label, for example from a raw `docker run` or `podman run`: `down` refuses it with `refusing to remove ... because it has no agentainer label`. Record its mounts and options with `docker inspect` or `podman inspect`, remove it with `docker rm` or `podman rm`, then create it with `bin/agentainer up`, using the same home volume and DIR.

**Files in `/workspace` belong to UID 1000 on a Linux host.**
That is rootful Docker with a host UID other than 1000. Build an image with your UID, or use Podman or rootless Docker ([file ownership](running.md#file-ownership)).

**An agent shows an old setting after an upgrade.**
The entrypoint adds the image's files only where your home volume has none, so new default settings in the image do not replace yours. Compare your files with the image's copies in `/etc/agentainer/home/`. [Upgrading](running.md#upgrading) lists the few files the entrypoint does change.

**`claude doctor` warns that `~/.local/bin` is not in `PATH` and says to run `claude install`.**
The image installs Claude Code at `/usr/local/bin/claude`, and a new image brings a new version. The warnings look for Anthropic's per-user install in `~/.local`, which the image does not use. Ignore them: `claude install` prints "Updates are disabled by your administrator" and changes nothing.

**`agentainer-mcp` warns that an agent "already has a server named ... that agentainer did not add".**
That agent's own config has a server with the same name, which the sync leaves alone. Rename one of them in `~/.agentainer/mcp.json` or in the agent.

**The tmux session does not start over SSH in Kubernetes: "open terminal failed: terminal does not support clear".**
tmux needs `TERM`. The webhook in `deploy/kubernetes` sets it; check that ContainerSSH uses that webhook's `/config` answer ([docs/kubernetes.md](kubernetes.md#logging-in)).
