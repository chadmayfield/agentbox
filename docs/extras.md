# Optional extras

`agentainer-extras` installs optional npm tools that the image pins but does not install: Kandev, OpenChamber and REA. Each extra installs from a lockfile in the image, with install scripts off, at the version the image pins.

## Contents

- [Commands](#commands)
- [Where extras go](#where-extras-go)
- [What install does](#what-install-does)
- [Upgrades and removal](#upgrades-and-removal)
- [Kandev](#kandev)
- [OpenChamber](#openchamber)
- [REA](#rea)
- [Known findings](#known-findings)
- [How the pins update](#how-the-pins-update)

## Commands

| Command | Effect |
|---|---|
| `agentainer-extras list` | Lists each extra with its pinned version, the installed version and a description. `-` means not installed. An installed version that differs from the pin shows `(outdated)`. |
| `agentainer-extras install NAME...` | Installs each named extra at its pinned version. Run it again after an image upgrade to move an `(outdated)` extra to the new pin. |
| `agentainer-extras remove NAME...` | Removes each named extra's files and bin links. |

Exit codes: 0 on success, 1 when an install or remove failed, 2 for a usage error or an unknown name. The command checks every name before it changes anything, so one unknown name installs or removes nothing. With several names, a failure for one name does not undo the others. `remove` also accepts a name absent from the catalog when its files are in the tools root, so an extra that a later image dropped can still be removed.

The command needs `/var/lib/agentainer/active`, the link the entrypoint creates at start. Without it, as in a container started without the entrypoint, the command exits 1 with a message.

## Where extras go

Extras go into the same tools root as `npm -g`, chosen by `AGENTAINER_TOOLS` ([Tools that agents install](configuration.md#tools-that-agents-install)):

| `AGENTAINER_TOOLS` | Install directory | Survives a new container |
|---|---|---|
| `ephemeral` (default) | `/var/lib/agentainer/tools/npm/extras/` | No |
| `persist` | `~/.agentainer/tools/npm/extras/` | Yes |

In ephemeral mode, `install` prints that the extra is gone when the container is replaced. To keep extras, start the container with `AGENTAINER_TOOLS=persist` and install them again.

Each install goes into its own directory, `npm/extras/<name>@<version>.<random>`. The link `npm/extras/<name>` points at the active one, and each command links from `npm/bin/<command>` through that link, so the command is on `PATH` like a tool from `npm -g`.

`agentainer-tools reset` moves the persisted tools root, extras included, to a dated backup. Install the extras again after a reset.

## What install does

`install` first takes the locks, once for all names. In persist mode it takes `~/.agentainer/.tools-reset.lock` first, so `agentainer-tools reset` cannot move the root during an install, then `npm/.extras.lock` in the tools root, so containers that share one home install one at a time. `remove` takes the same locks. When a lock is not free after 5 seconds, the command prints `waiting for <lock file>, held by another agentainer-extras install or remove, or by agentainer-tools reset` and keeps waiting.

Then, for each name, it:

1. Refuses to replace a file at `npm/bin/<command>` that is not its own link. Move the file aside and run `install` again.
2. Copies the catalog's `package.json` and `package-lock.json` into a new directory and runs `npm ci --ignore-scripts --no-audit --no-fund` there. `npm ci` installs exactly the lockfile and fails when the lockfile and `package.json` disagree ([npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci)). The lockfile records an `integrity` hash for every package ([package-lock.json](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json)), and a tarball that does not match fails the install ([`tests/65-extras.sh`](../tests/65-extras.sh) checks this). With `--ignore-scripts`, npm does not run the scripts in any package's `package.json` ([npm config](https://docs.npmjs.com/cli/v11/using-npm/config#ignore-scripts)), so `npm ci` runs no package code.
3. Checks that the installed package's version equals the pin.
4. Runs the extra's check command, for example `kandev --version`. A tool that cannot start fails here.
5. Creates any missing `npm/bin/<command>` links, switches the `npm/extras/<name>` link to the new directory and prints the extra's start notes.

Any failure before the `npm/extras/<name>` link switches removes the new directory and the bin links this run made, and leaves the previous install and its links untouched. On an npm failure the command prints where npm's log is.

`install` always installs the version the image pins. To get a different version, use an image that pins it.

## Upgrades and removal

An upgrade keeps the directory it replaced, because another container on the same home may still run it, and deletes it at the next install of that extra. Older directories are deleted at that point too.

`remove` deletes the `npm/extras/<name>` link, every `npm/extras/<name>@*` directory and the bin links into them. Files the tool created outside `npm/extras`, such as its data directory or settings in your home, stay. The command says so when it finishes.

## Kandev

[Kandev](https://github.com/kdlbs/kandev) is a web task board that runs coding agents and reviews their changes. npm package `kandev`, command `kandev`. License: AGPL-3.0-only ([npm metadata for kandev 0.98.0](https://registry.npmjs.org/kandev/0.98.0)).

Start it in a container started with a published port:

```sh
bin/agentainer up --publish 38429:38429 "$HOME/code"
# inside the container
kandev --port 38429 --headless
```

Then open `http://localhost:38429` on the host. The Kandev launcher runs a native runtime from an optional platform package, so this extra keeps optional dependencies. The install check is `kandev --version`, which fails when that runtime is missing.

Kandev's backend listens on `0.0.0.0` by default, and Kandev's documentation says its local mode "is not an authenticated multi-user boundary" ([Kandev CLI, Ports and network exposure](https://kandev.ai/docs/cli)). The same page says this "can expose Kandev to other machines on the network". The launcher publishes to `127.0.0.1` on the host unless the mapping names another address ([Development server ports](running.md#development-server-ports)).

In a Kubernetes pod, do not expose Kandev through a Service. Start it bound to loopback, as Kandev's documentation shows, and reach it with `kubectl port-forward` ([Kubernetes port forwarding](https://kubernetes.io/docs/tasks/access-application-cluster/port-forward-access-application-cluster/)):

```sh
# in the pod
KANDEV_SERVER_HOST=127.0.0.1 kandev --port 38429 --headless
# on your machine
kubectl -n agentainer port-forward pod/agentainer-0 38429:38429
```

Not verified: this has not been run in a cluster.

## OpenChamber

[OpenChamber](https://registry.npmjs.org/@openchamber/web) is a web interface for the OpenCode agent. npm package `@openchamber/web`, command `openchamber`. License: MIT, as its [README](https://unpkg.com/@openchamber/web@2.5.1/README.md) states. Its npm metadata has no license field ([npm metadata for @openchamber/web 2.5.1](https://registry.npmjs.org/@openchamber/web/2.5.1)).

OpenChamber starts on port 3000. `--lan` makes it listen on `0.0.0.0`, and `--ui-password` protects browser access ([README](https://unpkg.com/@openchamber/web@2.5.1/README.md)). To reach it from the host, use both:

```sh
bin/agentainer up --publish 3000:3000 "$HOME/code"
# inside the container
openchamber --lan --port 3000 --ui-password '<password>'
```

Then open `http://localhost:3000` on the host. Its terminal uses `node-pty`. The install check runs `openchamber --version` and loads `node-pty`'s prebuilt binding, since its install script never runs.

## REA

[REA](https://github.com/morluto/rea) is a reverse engineering CLI and MCP server. npm package `rea-agents`, commands `rea` and `rea-agents`. License: MIT ([npm metadata for rea-agents 6.8.0](https://registry.npmjs.org/rea-agents/6.8.0)).

Install does not add REA to any agent. Run `rea-agents setup --client <agent>`, for example with `claude_code`, `codex`, `opencode` or `antigravity`.

REA's terminal support uses `@lydell/node-pty`, whose native binding ships in optional platform packages, so this extra keeps optional dependencies. The install check runs `rea --version` and loads `@lydell/node-pty`.

The REA Frida tools do not work in this install. The optional `frida` package installs, but its install script, which fetches or builds its native binding, never runs. REA loads `frida` only when a Frida tool runs, and that tool then fails. The rest of REA does not load `frida`.

## Known findings

PLACEHOLDER: findings from the lockfile scan at the pins in versions.env; filled after the OpenChamber pin update.

## How the pins update

`versions.env` pins `KANDEV_VERSION`, `OPENCHAMBER_VERSION` and `REA_VERSION`. Each extra's dependency tree, with an `integrity` hash for every package, is in `rootfs/usr/local/share/agentainer/extras/<name>/package-lock.json`. The scheduled update proposes a newer version only when it was published at least 7 days earlier, applies the same age limit to every dependency, and checks every lockfile entry against npm's registry signatures. [Versions: optional extras](versions.md#optional-extras) describes the checks.
