# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for a security problem.

Include what you found, how to reproduce it, and the exact image reference you used, with its tag or digest (for example `ghcr.io/chadmayfield/agentainer@sha256:...`). This command shows the image's version label, which helps but does not identify the image on its own; a local build reports `dev`:

```sh
docker image inspect <image> --format '{{index .Config.Labels "org.opencontainers.image.version"}}'
```

## What is in scope

- The image build: `Containerfile`, `build/`, and the pins in `versions.env`.
- The scripts the image ships in `rootfs/`, such as the entrypoint and `agentainer-mcp`.
- The launcher `bin/agentainer`.
- The Kubernetes example in `deploy/kubernetes/`, including the auth webhook.
- The Kelos variant: `Containerfile.kelos`, `rootfs-kelos/` and `tests/kelos/`.
- The CI workflows in `.github/workflows/`.

A vulnerability in an agent or tool that the image installs (Claude Code, Codex, Antigravity CLI, OpenCode, Go, gh and the others) belongs to that project. Report it there. Once the project ships a fix, a scheduled or manually triggered version bump brings it into the image.

## Supported versions

Fixes ship in new releases; older images are not rebuilt under the same version. Releases use SemVer, including dated development prereleases such as `0.1.0-dev.20261019.1`. The image tag `latest` follows the highest stable release. Prereleases require an explicit version tag, and `latest` does not exist before the first stable release. See the [release policy](docs/versions.md#releases).

## Known limits

[docs/security.md](docs/security.md) lists what the container does and does not isolate. Every supplied credential is available to container code, and agents can modify mounted files that the host later executes. The example ContainerSSH webhook serves plain HTTP. TLS requires server-side changes or a TLS-terminating proxy; there is no webhook TLS switch.

Each release lists its trivy findings in the release notes and attaches the full reports ([docs/security.md](docs/security.md#vulnerability-reports)).
