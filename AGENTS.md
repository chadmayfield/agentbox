# AGENTS.md

Rules for anyone changing this repository: AI coding agents and people. Claude Code, Codex, Antigravity CLI and OpenCode all read this file. Do not add a `CLAUDE.md` at the repo root: by default, Claude Code reads `AGENTS.md` only when no `CLAUDE.md` exists in the working directory or above it ([Claude Code memory](https://code.claude.com/docs/en/memory)). The image's seeded `rootfs/etc/agentainer/home/.claude/CLAUDE.md` is a different file. [CONTRIBUTING.md](CONTRIBUTING.md) covers branches, CI and releases.

## What this repo is

Agentainer is one public container image that bundles four AI coding agents (Claude Code, Codex CLI, Antigravity CLI, OpenCode) and a shared toolset. It runs locally with Podman or Docker and in Kubernetes through ContainerSSH.

| Path | Contents |
|---|---|
| `Containerfile`, `build/` | The image build and the scripts it runs |
| `versions.env` | Every pinned version, digest and checksum |
| `rootfs/` | Files copied into the image: the entrypoint and its steps, `agentainer-*` commands, seeded configs |
| `bin/agentainer` | The host launcher (POSIX sh) |
| `deploy/kubernetes/` | The Kubernetes example: StatefulSet, ContainerSSH, auth webhook |
| `scripts/` | Build, scheduled pin update, CI report scripts |
| `tests/` | Container tests (`NN-*.sh`), host tests (`host/`), unit tests (`unit/`), fixtures |
| `docs/` | User documentation |
| `.github/workflows/` | CI, release and the scheduled update |
| `Containerfile.kelos`, `rootfs-kelos/`, `tests/kelos/` | The Kelos variant image, its files and its tests ([docs/kelos.md](docs/kelos.md)). Its pins live in `Containerfile.kelos`, not `versions.env`. CI does not build or test it. |

`docs/private/` holds the maintainer's design notes, may be stale, and is ignored by git. Never commit anything under it.

## Commands

```sh
scripts/build.sh                            # build localhost/agentainer:dev
sh tests/run.sh [tests/NN-name.sh ...]      # container tests
sh tests/lint.sh                            # shellcheck, shfmt and Ruff
python3 -m unittest discover -s tests/unit
sh tests/14-unit-linux.sh                   # image Python and Linux-only unit modules
sh tests/host/test-launcher.sh
sh tests/host/test-build-script.sh
sh tests/host/test-fetch.sh
sh tests/host/test-manifests.sh
sh tests/host/test-launcher-integration.sh  # real engine, existing local image
sh tests/host/test-build-uid.sh             # slow: full build with --uid 1001 --gid 20
python3 tests/host/test-layer-repro.py      # slow: two clean tool builds, configured Buildx
python3 tests/host/test-healthcheck.py      # also invoked by tests/58-healthcheck.sh
python3 tests/host/test-language-tooling.py --image localhost/agentainer:dev  # slow, network
python3 tests/host/test-playwright-setup.py --image localhost/agentainer:dev  # slow, network
scripts/build.sh --variant kelos [--from IMAGE]                 # build localhost/agentainer-kelos:dev; network
IMAGE=localhost/agentainer-kelos:dev sh tests/kelos/test_image.sh
# Release verification arguments: docs/versions.md#verifying-a-release-before-use
# Optional terminal screenshots: tests/visual/README.md
```

Check each command's exit code directly. Piping into `tail` or `grep` hides a failure.

## Verify, never guess

- Every package name, version, install command, config path, file name, flag and URL must come from the tool's official docs, its official repository, or a command you ran. Cite the source next to the fact in docs and in commit or pull request text.
- If you cannot verify something, write "not verified" and ask the maintainer. If sources disagree, show both and let the maintainer choose.
- Check a CLI flag with `--help`, a man page or the tool's source before you use it.
- A recommendation is not a decision. Design changes need the maintainer's approval first.

## Public and generic

- The repo is public and MIT licensed. Anyone must be able to use it.
- Never commit internal information: hostnames, IP addresses, cluster names, registry names, domains or network details from anyone's own infrastructure. Use `example.com` and `203.0.113.0/24` in examples.
- Never put credentials in the image, in any layer, or in the repo. Credentials come in at run time through environment variables or the home volume.

## Pins and downloads

- Every pinned version, digest and checksum for the image lives in `versions.env`. Do not hardcode versions in the `Containerfile` or scripts. Exceptions: GitHub Actions and the actionlint image are pinned by SHA or digest in the workflow files, and the two image references in `deploy/kubernetes/*/deployment.yaml` repeat their `versions.env` pins (`bump_versions.py` rewrites them and `tests/host/test-manifests.sh` checks they match).
- A new pin needs a resolver in `scripts/bump_versions.py`, unless the scheduled update must never change it (`SOURCE_DATE_EPOCH`). Its key must match a pattern in `VALUE_PATTERNS` (most keys match by suffix, such as `_VERSION` or `_SHA256_ARM64`). The scheduled update refuses to write a value that matches no pattern.
- Check every download against the checksum the project publishes. When a project publishes none, record the SHA-256 you computed and say so in a comment.
- Install upstream release binaries. Do not build a tool from source to pick up a newer Go, Rust or library version.

## Vulnerabilities in bundled tools

- Findings inside an upstream binary are reported, not chased. A new upstream release reaches the image through the scheduled update.
- When a tool stops shipping releases and carries a critical finding that only a rebuild would fix, the maintainer decides whether to keep, drop or replace it. Record the decision in the pull request that makes it.

## Image and runtime

- Image-owned files live outside `/home/agent`. Initial, agent-owned `.profile` and `.bashrc` seed copies are the exception, so a newly created named home volume receives shell defaults. They become user files and startup does not replace them.
- The entrypoint never replaces a user's file with the image's copy; it only adds files that are missing. These exceptions each change only what they manage ([docs/running.md](docs/running.md#upgrading)):
  - `~/.agentainer/AGENTS.md` is replaced with a new image default only when it is a regular file the user never edited and `release_version.py newer-default` finds the image's release version newer than every version that shipped the current content (`30-agents-md.sh`). Local `dev` builds never replace it.
  - `agentainer-mcp sync` edits only the MCP servers recorded in `~/.agentainer/mcp-managed.json`.
  - `gh auth setup-git` and the git identity step write `~/.gitconfig`.
  - The OpenCode step runs `opencode service set disabled true` only when `~/.config/opencode/service.json` does not exist yet, which creates that file.
- Containers may share one home volume. Anything that writes to it must cope with another container doing the same at the same time (unique temp files, `flock`).
- Shell scripts are POSIX sh unless they need bash, and must pass `shellcheck` and `shfmt`. `/bin/sh` in the image is dash.

## Tests

- Add or change a test with each behavior change. A bug fix starts with a test that fails; run it and watch it fail before you fix the code.
- A test must be able to fail. A check that something is absent uses `assert_absent` with a marker that proves the command ran. Running the suite with `IMAGE=localhost/agentainer:no-such-image` must print no `ok` line.
- Container tests must not need the network unless the behavior is about the network. Use the fixtures in `tests/fixtures/`.
- Run the tests before asking for a commit, and report the real results, including failures.

## Git

- Follow the branch rules in [CONTRIBUTING.md](CONTRIBUTING.md). Never push to `main` and never run `git flow release finish`.
- Before each commit, show a file-by-file summary of what changed and wait for the maintainer's approval.
- When an AI agent writes a commit, end the message with a `Co-Authored-By` trailer that names that agent, with the address its maker documents for this purpose. Claude Code uses:

  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

  If your maker documents no address, ask the maintainer before you commit.

- Sign maintainer-authored local commits and release tags with the configured signing key. Never disable signing to bypass a failure. Repo-local signing settings are not shared with contributors or CI.
- A release requires a signed annotated tag on the matching release merge in `main`. CI verifies it against `RELEASE_SIGNING_FINGERPRINT`; never put a private key in CI or the image.
- Do not force-push, rewrite published history, or delete branches without explicit instruction.

## Working on the host

- Do not install software on the maintainer's machine without asking first.
- Building and running containers locally is allowed. Remove the test containers, volumes and images you create.
- Do not deploy to any Kubernetes cluster without explicit approval for that deployment.

## Writing

These rules apply to docs, commit messages, pull request text, code comments and user-facing messages.

- Plain, direct sentences in active voice. Sentence-case headings.
- No em dashes. Use periods or commas.
- No filler ("in order to", "it is important to note"), no hype words ("seamless", "robust", "powerful"), no emojis.
- Say what a thing does, with the command, path or number, not how it feels.
- Code comments describe what the code does and why, as a developer would write them. No history ("now", "no longer", "fixed"), no references to reviews, tasks, plans or private notes.
