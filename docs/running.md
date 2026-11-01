# Running Agentainer with Podman or Docker

This page covers the launcher, raw `docker run` and `podman run` commands, health checks, sudo, file ownership and upgrades.

## Contents

- [The launcher](#the-launcher)
- [Development server ports](#development-server-ports)
- [Without the launcher](#without-the-launcher)
- [Container health](#container-health)
- [sudo](#sudo)
- [File ownership](#file-ownership)
- [Other options](#other-options)
- [Upgrading](#upgrading)

## The launcher

[`bin/agentainer`](../bin/agentainer) wraps the `run` and `exec` commands below. It uses Podman when it finds it, otherwise Docker, and prints each command before it runs it.

| Command | What it does |
|---|---|
| `agentainer up [--name N] [--sudo] [--image I] [--publish MAPPING ...] [--] [DIR]` | Starts a detached container. DIR defaults to the current directory and becomes `/workspace`. |
| `agentainer attach [N]` | Runs `tmux new-session -A -s main` in the container |
| `agentainer shell [N]` | Opens a bash login shell |
| `agentainer start [N]` | Starts a stopped container, for example after the host or the Podman machine restarts |
| `agentainer update [N]` | Pulls the image the container was created from and recreates the container with the same options ([upgrading](#upgrading)) |
| `agentainer down [N]` | Removes a container carrying the Agentainer label. It refuses unrelated containers. The home volume stays. |
| `agentainer status` | Lists agentainer containers |
| `agentainer doctor [N] [--json]` | Runs offline diagnostics in the running container, without a TTY; see [diagnostic checks and exit codes](troubleshooting.md#offline-diagnostics). |

N defaults to `agentainer`. These variables override the launcher's defaults:

| Variable | Default |
|---|---|
| `AGENTAINER_IMAGE` | `ghcr.io/chadmayfield/agentainer:latest` |
| `AGENTAINER_ENV_FILE` | `~/.config/agentainer/env` |
| `AGENTAINER_HOME_VOLUME` | `agentainer-home` |
| `AGENTAINER_RUNTIME` | `podman` if installed, else `docker` |

For a host directory instead of the default named home volume, set `AGENTAINER_HOME_VOLUME` to an existing directory such as `"$HOME/.config/agentainer/home"`. Both mount at `/home/agent`. [Customizing Agentainer](customization.md) covers setup, your own dotfiles and separate test homes.

Home sources containing `/`, or exactly `.` or `..`, are host paths. Other values are named volumes. Use `./myhome` for a relative directory rather than `myhome`. The launcher warns if a mount exposes the host home, a parent of it, or the host root. Choose a project directory to limit access.

Limits:

- DIR must not contain `:`, because `-v` splits its value at `:`. Rename the directory to remove `:`.
- Container names also serve as hostnames. They must be at most 64 ASCII characters and start with a letter or digit ([launcher](../bin/agentainer), [hostname limit](https://man7.org/linux/man-pages/man2/sethostname.2.html)).
- `update` pulls from a registry, so it cannot update a container that runs an image you built locally (`localhost/...`). Use `agentainer down` and `agentainer up --image ...` for those.

## Development server ports

Repeat `--publish` or `-p` before DIR to publish development servers to the host:

```sh
bin/agentainer up --publish 3000:3000 --publish 8080:8000 "$HOME/code"
```

This maps host ports 3000 and 8080 to container ports 3000 and 8000. Open `http://127.0.0.1:8080` on the host for a server on container port 8000. The server must listen on the container's network interface, for example `0.0.0.0`, not only on its own loopback address ([Docker publishing](https://docs.docker.com/engine/network/port-publishing/), [Podman publishing](https://docs.podman.io/en/latest/markdown/podman-run.1.html)).

Each mapping is `[IPv4:]HOST_PORT:CONTAINER_PORT[/tcp|udp]`:

| Form | Example | Result |
|---|---|---|
| No address | `--publish 3000:3000` | Binds `127.0.0.1` on the host, TCP |
| UDP | `--publish 5353:5353/udp` | UDP instead of TCP |
| Explicit address | `--publish 0.0.0.0:3000:3000` | Binds all host IPv4 interfaces |
| Joined forms | `--publish=3000:3000`, `-p3000:3000` | Accepted |
| IPv6, port ranges, automatic host ports | | Not supported; use a direct runtime command |

Ports must be 1 through 65535. For a remote engine, the bind address belongs to the engine host. With a local VM, reachability also depends on the runtime's port forwarding.

The launcher validates mappings before it creates a container and before it pulls an update. With no `--publish` option, it publishes no ports. `update` keeps the recorded mappings. Containers created by older launchers without a ports label publish no ports. To change the mappings, recreate the container with new `up` options; the home stays.

## Without the launcher

Use a published version tag. The registry has no `latest` manifest until a stable release publishes it ([release policy](versions.md#releases)).

```sh
docker run -d --name agentainer --hostname agentainer \
  --security-opt no-new-privileges=true \
  --sysctl "net.ipv4.ping_group_range=1000 1000" \
  -v agentainer-home:/home/agent \
  -v "$HOME/code:/workspace" -w /workspace \
  --env-file "$HOME/.config/agentainer/env" \
  ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261024.1
docker exec -it agentainer tmux new-session -A -s main
```

With Podman, use the same commands and add `--userns=keep-id:uid=1000,gid=1000`. It maps your host user to the container user, so files in `/workspace` stay yours (`man podman-run`).

- The container runs `sleep infinity` under `tini` as PID 1. Sessions are `exec` calls into tmux, so agents keep running when a terminal or SSH connection drops.
- The whole home directory `/home/agent` is one volume. Logins, settings and `AGENTS.md` live there and survive a new container. Containers that use the same volume share logins, and two containers running the same agent write the same files.
- The `ping_group_range` sysctl lets `ping` work without the `NET_RAW` capability. It names only GID 1000: with Podman's keep-id the GID map is not contiguous, and a wider range breaks.

## Container health

The image runs [`agentainer-healthcheck`](../rootfs/usr/local/bin/agentainer-healthcheck) through the [Dockerfile `HEALTHCHECK` instruction](https://docs.docker.com/reference/dockerfile/#healthcheck):

| Setting | Value |
|---|---|
| Interval | 30 seconds |
| Timeout | 5 seconds |
| Start period | 180 seconds |
| Retries before `unhealthy` | 3 |

The probe checks the entrypoint's completion marker, read, write and search access to the home directory, and that the active tools symlink points to a readable, searchable directory. Startup clears the marker, including after a restart. The probe reads no agent settings or credentials, runs no agents, changes no home files and makes no network requests. It does not check free disk space or whether each tool works. [`agentainer doctor`](troubleshooting.md#offline-diagnostics) checks configuration syntax and that tools start; neither checks free space, so use `df -h` for that.

Inspect the status and recent probe results from the host:

```sh
podman inspect --format '{{json .State.Health}}' agentainer
docker inspect --format '{{json .State.Health}}' agentainer
```

Health status reports readiness. It does not restart the container. Kubernetes ignores image health checks; configure pod probes separately ([Kubernetes probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)).

Podman inherits an image health check only from a Docker-format manifest ([Podman source](https://github.com/containers/podman/blob/v5.3.2/pkg/specgen/generate/container.go#L67-L87)). `scripts/build.sh` builds Docker format with both engines. Release images are OCI manifests with SBOM and provenance attestations, so a raw `podman run` of a release image needs the probe passed explicitly:

```sh
--health-cmd=/usr/local/bin/agentainer-healthcheck --health-interval=30s \
--health-timeout=5s --health-start-period=180s --health-retries=3
```

The launcher does not add these options ([Podman options](https://docs.podman.io/en/v5.3.2/markdown/podman-run.1.html#health-cmd-command)). Older images without the probe need an image update and a new container. [Troubleshooting](troubleshooting.md#common-problems) covers Podman-specific health states.

## sudo

The image has passwordless sudo, and `--security-opt no-new-privileges=true` turns it off ([Docker reference](https://docs.docker.com/reference/cli/docker/container/run/)). `agentainer up --sudo` leaves that option out.

With sudo on, an agent can change anything in the container, including the agent binaries and the settings that stop them from updating themselves. Packages installed with `sudo apt install` are gone when the container is recreated. Under rootful Docker, container root is UID 0 on the host, limited by the container's namespaces.

## File ownership

- Rootless Podman with keep-id: files in `/workspace` belong to your host user.
- Rootful Docker on Linux: files written to `/workspace` belong to UID 1000 on the host. If your UID is different, use Podman or rootless Docker, or build an image with your UID and GID.

`scripts/build.sh` uses Podman unless `RUNTIME` says otherwise. On a Docker host:

```sh
RUNTIME=docker sh scripts/build.sh --uid "$(id -u)" --gid "$(id -g)"
```

With a GID other than 1000, also set `--sysctl "net.ipv4.ping_group_range=<gid> <gid>"` in your `run` command, or `ping` fails. The launcher always passes `1000 1000`.

`sh tests/host/test-build-uid.sh` builds an image with `--uid 1001 --gid 20` and checks the agent user. When the build fails, it prints the last 80 lines of the build output.

## Other options

- SSH agent on a Linux host: add `-v "$SSH_AUTH_SOCK:/run/ssh-agent.sock" -e SSH_AUTH_SOCK=/run/ssh-agent.sock`. A forwarded agent lets container processes request signatures with its loaded keys, so use a dedicated agent holding only the keys this session needs ([credential exposure](security.md#what-the-container-isolates)). `ssh-agent` refuses a client whose UID differs from its own unless the client is root (`uid mismatch` in [ssh-agent.c](https://github.com/openssh/openssh-portable/blob/master/ssh-agent.c)), so the container user needs the UID of the user who started the agent:
  - Rootless Podman with keep-id, as the launcher runs it, maps your host UID to the container user ([podman-run](https://docs.podman.io/en/latest/markdown/podman-run.1.html)). Not verified with an SSH agent.
  - Rootful Docker runs the container user as UID 1000. If your UID is different, build your own image as described in [File ownership](#file-ownership).

  Verified in CI with rootful Docker on Linux only, in a narrow check: CI makes the socket's directory readable, then runs `ssh-add -l` as the entrypoint with `--user "$(id -u):$(id -g)"`, so the normal entrypoint does not run. Not verified: macOS, where the socket path depends on the runtime. For git, the default is `GH_TOKEN` ([logins](logins.md)).
- SELinux hosts may need `:z` on volume mounts. Not verified.

## Upgrading

```sh
bin/agentainer update
```

`update` pulls the image the container was created from and recreates the container; the home volume stays. Without the launcher, pull first: a plain `run` does not pull a newer image for a tag that is already on your machine. For Kubernetes, see [docs/kubernetes.md](kubernetes.md#upgrading-and-removing).

How `update` works:

- `up` records DIR, image, sudo setting, home volume, published ports and the env file's absolute path as container labels. `update` reads them back.
- `update` changes nothing when the pull fails, when DIR or the env file no longer exists, or when the container has no option labels.
- After the pull, `update` renames the old container to `cx-agentainer-backup-N` and stops it. It removes the backup only after the new container starts. If creation or startup fails, it restores the old container in its previous running or stopped state. Changes the new container made to the home or workspace are not rolled back.
- Startup may take up to 180 seconds. The new container counts as started when the entrypoint's completion marker exists; for an older image without the marker, when its tools link exists. If the launcher is killed before it can restore a failed update, inspect `cx-agentainer-backup-N` before you retry. `update` refuses to overwrite an existing backup.
- A successful `update` leaves the new container running, even when the old one was stopped.
- `AGENTAINER_DRY_RUN=1` prints the commands that change state instead of running them. `update` and `down` still run read-only `inspect` calls to read the recorded options.

On the first start of the new image, the entrypoint adds files that are missing from your home volume. It does not replace your files with the image's copies, with these exceptions. Each exception changes only the part the entrypoint manages:

| File | What changes | When |
|---|---|---|
| `~/.agentainer/AGENTS.md` | Replaced with the new default | You never edited it and the image's version allows it; [AGENTS.md](configuration.md#agentsmd) lists the conditions |
| Agent MCP configs | Servers that `agentainer-mcp sync` added | `~/.agentainer/mcp.json` changed, or you run `agentainer-mcp sync` ([MCP servers](configuration.md#mcp-servers)) |
| `~/.gitconfig` | The GitHub credential helper, from `gh auth setup-git` | `GH_TOKEN` or `GITHUB_TOKEN` is set and this container's `gh` is not already the helper ([GitHub and Git](logins.md#github-and-git)) |
| `~/.gitconfig` | `user.name` or `user.email` | `GIT_AUTHOR_NAME` or `GIT_AUTHOR_EMAIL` is set and the file has no value for it |
| `~/.config/opencode/service.json` | Created by `opencode service set disabled true` | The file does not exist yet |

Everything else:

- Logins, agent settings and history stay.
- New defaults in the image's seed files do not reach an existing home. Compare yours with the image's copies in `/etc/agentainer/home/`, for example `.claude/settings.json` and `.codex/config.toml`.
- With `AGENTAINER_TOOLS=persist`, tools you installed stay on `PATH` after the image's own tools ([tools that agents install](configuration.md#tools-that-agents-install)).
- MCP servers sync again only when `~/.agentainer/mcp.json` changes. Run `agentainer-mcp sync` to sync after an upgrade.
- Anything installed with `sudo apt install` is gone, as after every new container.
