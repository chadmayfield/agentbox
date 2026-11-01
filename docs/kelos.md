# Kelos variant

The Kelos variant is a second image, built from [`Containerfile.kelos`](../Containerfile.kelos) on top of a published Agentainer image. It runs the Claude Code and Codex agents under [Kelos](https://github.com/kelos-dev/kelos), which starts agent containers as UID 61100 with `/kelos_entrypoint.sh`. Provenance and changes to the upstream files are in [`rootfs-kelos/SOURCE.md`](../rootfs-kelos/SOURCE.md).

## Contents

- [What it adds](#what-it-adds)
- [Building and testing](#building-and-testing)
- [Pins](#pins)

## What it adds

| Path in the image | What it is |
|---|---|
| `/kelos_entrypoint.sh` | Dispatcher written for this image. It runs the Kelos entrypoint for `KELOS_AGENT_TYPE` (`claude-code` or `codex`) and refuses a Claude pod that sets another Claude authentication source, such as `ANTHROPIC_API_KEY` or a cloud-provider selector, or a settings file with a credential helper. Claude's credential is `CLAUDE_CODE_OAUTH_TOKEN`. |
| `/kelos_entrypoint_claude.sh`, `/kelos_entrypoint_codex.sh` | Kelos v0.62.0 entrypoints. The Codex one carries six marked changes listed in `SOURCE.md`. |
| `/kelos/kelos-capture` | Built from source from the `chadmayfield/kelos` fork, not the upstream binary. It reads pull requests over REST instead of GraphQL. |
| `/usr/local/bin/gh` | Kelos's gh wrapper, which reads the token from `KELOS_GITHUB_TOKEN_FILE`. The real `gh` moves to `/usr/bin/gh`. |
| `/usr/local/bin/push-sidecar` | Pushes the agent's work to a branch while a Task runs, as a sidecar container |
| `/usr/local/lib/kelos/` | The guard, a `claude` wrapper and the MCP header helper |

Other differences from the main image:

- It runs as user `kelos` (UID 61100) with home `/home/kelos`. Tool install locations (`GOBIN`, `NPM_CONFIG_PREFIX`, `CARGO_INSTALL_ROOT`, uv and pipx) point into that home, because the Agentainer entrypoint does not run.
- The entrypoint is `tini -g -- /kelos_entrypoint.sh`, and the image has no health check.
- It adds no apt packages.
- It refuses Kelos's `KELOS_MCP_SERVERS` and reads one MCP server from files mounted at `/etc/agentainer/mcp`. `SOURCE.md` describes the rules.

## Building and testing

```sh
scripts/build.sh --variant kelos                                   # tag localhost/agentainer-kelos:dev
scripts/build.sh --variant kelos --from localhost/agentainer:dev   # on another base image
IMAGE=localhost/agentainer-kelos:dev sh tests/kelos/test_image.sh
```

- Without `--from`, the build uses the digest-pinned `0.1.0-dev.20261024.1` image named in `Containerfile.kelos`.
- `--tag` sets another tag. `RUNTIME=docker` builds with Docker.
- The `kelos-capture` stage needs network access to github.com and the Go module proxy.
- The tests need no network. They check the user, the entrypoints, the agent binaries, the gh wrapper and the credential guard.

CI does not build or test the variant, and no release publishes it.

## Pins

The variant's pins live in `Containerfile.kelos`, not in `versions.env`: the base Agentainer image digest, the `golang` builder image digest, `KELOS_FORK_COMMIT` and `KELOS_CAPTURE_VERSION`. The scheduled update does not change them.
