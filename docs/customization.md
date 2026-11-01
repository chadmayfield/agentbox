# Customizing Agentainer

Keep personal configuration in the persistent container home, `/home/agent`. You can edit it without rebuilding the image. Agentainer seeds missing files on startup and keeps existing files. See [default configuration](defaults.md) for the files it supplies and [upgrade behavior](running.md#upgrading) for the limited settings startup manages.

## Contents

- [Choose a persistent home](#choose-a-persistent-home)
  - [Named volume](#named-volume)
  - [Host directory](#host-directory)
- [Use your own configuration files](#use-your-own-configuration-files)
- [Image upgrades and separate test homes](#image-upgrades-and-separate-test-homes)
- [Customize the image itself](#customize-the-image-itself)
- [Project dependencies and installed tools](#project-dependencies-and-installed-tools)

## Choose a persistent home

Both methods survive container removal and recreation:

| Method | Launcher setting | Where files live |
|---|---|---|
| Named volume | `AGENTAINER_HOME_VOLUME=agentainer-home` | Docker or Podman manages the storage |
| Bind mount | `AGENTAINER_HOME_VOLUME="$HOME/.config/agentainer/home"` | A directory you can edit and back up on the host |

A bind mount is useful when you want to maintain your own dotfiles from the host. The launcher mounts the directory at `/home/agent`; the host path does not need to match the container path.

Run the examples from the repository root. They assume `$HOME/code` already exists and use a local image built with `sh scripts/build.sh`:

```sh
export AGENTAINER_IMAGE=localhost/agentainer:dev
```

You can instead set `AGENTAINER_IMAGE` to a published image's full registry reference and version tag. See [release versions](versions.md#releases). Choose one home method below for a new container named `agentainer`.

### Named volume

This is the launcher's default:

```sh
AGENTAINER_HOME_VOLUME=agentainer-home bin/agentainer up "$HOME/code"
bin/agentainer attach
```

### Host directory

Create the directory before starting the container. The subshell's private umask applies to newly created directories:

```sh
(
  umask 077
  mkdir -p "$HOME/.config/agentainer/home"
)
AGENTAINER_HOME_VOLUME="$HOME/.config/agentainer/home" \
  bin/agentainer up "$HOME/code"
bin/agentainer attach
```

The resulting home mount is `-v "$HOME/.config/agentainer/home:/home/agent"`. Creating that directory alone does not mount it; the launcher setting selects it ([launcher implementation](../bin/agentainer)). Use a dedicated container home directory rather than mounting your entire host home.

The home must be writable by the container user. The launcher uses Podman's keep-id mapping. With rootful Docker Engine on Linux, writes use the image's UID and GID, normally `1000:1000`; an existing host directory may have different ownership. Follow [file ownership](running.md#file-ownership) rather than making the directory writable by everyone. With a remote engine, the bind source must be accessible to that engine, including its VM or file-sharing configuration.

## Use your own configuration files

Before the first start, place the files you want to supply in the dedicated home directory. Agentainer fills the missing files around them. Alternatively, start with an empty directory and edit the seeded files afterward ([seeding implementation](../rootfs/usr/local/lib/agentainer/entrypoint.d/20-seed.sh)).

For the bind mount above:

| Configure | Host file under `~/.config/agentainer/home/` | File inside the container |
|---|---|---|
| Shell | `.bashrc` | `~/.bashrc` |
| Shell colors | `.config/agentainer/shell-theme.bash` | `~/.config/agentainer/shell-theme.bash` |
| tmux | `.tmux.conf` | `~/.tmux.conf` |
| Vim | `.vimrc` and `.vim/` | `~/.vimrc` and `~/.vim/` |
| Git identity, signing and aliases | `.gitconfig` | `~/.gitconfig` |
| Shared agent instructions | `.agentainer/AGENTS.md` | `~/.agentainer/AGENTS.md` |
| Claude Code | `.claude/settings.json` | `~/.claude/settings.json` |
| Codex | `.codex/config.toml` | `~/.codex/config.toml` |
| Antigravity | `.gemini/antigravity-cli/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| OpenCode | `.config/opencode/opencode.json` and `cli.json` | `~/.config/opencode/opencode.json` and `cli.json` |

The paths and supported settings are documented in [default configuration](defaults.md). Agent configuration files that select plugins, hooks or status-line commands also need those plugins or commands available inside the container. See [setting up the agents](agents.md) for each agent's settings, skills and status line, and [optional plugins](plugins.md) for install commands. A host-specific command or absolute symlink target does not become available merely because its configuration file is mounted.

With a named volume, open a shell with `bin/agentainer shell` and edit the same container paths. With a bind mount, changes made from either side affect the same files. Restart the affected application when it does not reload a changed setting automatically.

Git identity is personal. Set it in your home `.gitconfig` or supply the runtime identity variables described in [logins](logins.md#github-and-git). Keep credentials out of custom image builds and public dotfiles. The home can contain agent login credentials, so treat its backups as private data.

## Image upgrades and separate test homes

New image defaults are available under `/etc/agentainer/home/` inside the container. Compare them with your own files and apply the changes you want. Do not copy the entire seed directory over an existing home. [Upgrading](running.md#upgrading) lists the files that startup does change.

Mounts are selected when a container is created. Changing `AGENTAINER_HOME_VOLUME` does not change an existing container's mount or migrate files from its old home. `bin/agentainer down` removes the container and keeps its home; a subsequent `up` can select another home ([launcher commands](running.md#the-launcher)).

To try defaults independently, use another empty home directory and another container name:

```sh
(
  umask 077
  mkdir -p "$HOME/.config/agentainer/home-test"
)
AGENTAINER_HOME_VOLUME="$HOME/.config/agentainer/home-test" \
  bin/agentainer up --name agentainer-test "$HOME/code"
bin/agentainer attach agentainer-test
```

A separate home keeps its settings and logins separate. The workspace and runtime environment are still the ones you select. The launcher uses `~/.config/agentainer/env` by default; set `AGENTAINER_ENV_FILE` to another file when the test container should receive different runtime credentials. Prefer separate homes for independent profiles; containers sharing a home also share application state ([runtime configuration](running.md#without-the-launcher)).

## Customize the image itself

Rebuild when you want different defaults for new homes or a different bundled toolset:

- Edit seed files under `rootfs/etc/agentainer/home/`.
- Edit the shared instruction default at `rootfs/etc/agentainer/AGENTS.md`.
- Edit `build/apt-packages.txt` for OS packages. Update image and tool pins in `versions.env`, following the [pinning rules](../AGENTS.md#pins-and-downloads).
- Build your own tag with `sh scripts/build.sh --tag localhost/my-agentainer:dev` and select it with `AGENTAINER_IMAGE` or `bin/agentainer up --image` ([build script](../scripts/build.sh)).

Rebuilding does not replace existing home files. To keep user-installed tools across container recreation, see [tools that agents install](configuration.md#tools-that-agents-install).

## Project dependencies and installed tools

Use a project's dependency files and lockfile for its tests, linters and application libraries. [Project-local tooling](project-tools.md) gives Python/uv and JavaScript/npm examples. Agentainer does not create these files or install project dependencies at startup.

Project environments such as `.venv` and `node_modules` live under the project directory. Under `/workspace`, their files are on the workspace bind mount, independently of `AGENTAINER_TOOLS`. Recreate them from the lockfile when changing the container architecture or Python/Node runtime; dependencies may contain native binaries ([uv environment portability](https://docs.astral.sh/uv/concepts/projects/layout/#the-project-environment), [npm platform selection](https://docs.npmjs.com/cli/v9/configuring-npm/package-json#cpu)).

Caches and installed environments can be rebuilt; keep the project's dependency declarations and lockfiles in version control. For commands you want across projects, see [tools that agents install](configuration.md#tools-that-agents-install).
