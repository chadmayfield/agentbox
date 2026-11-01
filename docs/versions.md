# Versions, updates and releases

This page covers what the image pins, how pins are updated, which release tag to pull and how to verify a release.

## Contents

- [Pinned inputs](#pinned-inputs)
- [Agents do not update themselves](#agents-do-not-update-themselves)
- [Scheduled updates](#scheduled-updates)
- [Releases](#releases)
- [Verifying a release before use](#verifying-a-release-before-use)
- [Upstream publisher verification](#upstream-publisher-verification)
  - [Node.js release keyring](#nodejs-release-keyring)

## Pinned inputs

[`versions.env`](../versions.env) pins every input of the main image (`Containerfile`): the base image digest, the apt snapshot date, each agent and tool version, and the checksum of every download. The build checks each download against it. The one exception is the Rust toolchain: `rustup-init` downloads the components and checks each against the hashes in Rust's own channel manifest. The [Kelos variant](kelos.md#pins) keeps its pins in `Containerfile.kelos`.

Node.js is the official Linux tarball from nodejs.org, installed in `/opt/node` with `node`, `npm` and `npx` linked into `/usr/local/bin`. `versions.env` pins `NODE_VERSION` and the two Linux checksums (`NODE_SHA256_AMD64`, `NODE_SHA256_ARM64`), and the scheduled update follows the 26.x line. The image removes `include/`, `share/`, `README.md` and `CHANGELOG.md` from the install. Verification happens in two places: the updater checks the GPG signature on Node.js's checksum list before it writes the pins ([Node.js release keyring](#nodejs-release-keyring)), and the build checks the downloaded tarball against the pinned SHA-256 (`build/install-tool.sh`).

Claude Code is the native binary from Anthropic's release host, the file Anthropic's native installer downloads. The scheduled update checks the release's `manifest.json` against Anthropic's GPG signature before it pins the binary's SHA-256 ([binary integrity](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)).

Each tool is built in its own stage, so an update downloads only the layers that changed:

| Condition | Effect on layer digests |
|---|---|
| Release build, tool unchanged, same BuildKit (`BUILDKIT_IMAGE`) | Byte-identical to the previous release's layer. File times later than `SOURCE_DATE_EPOCH` are set to it (BuildKit's `rewrite-timestamp` option). |
| Release that updates BuildKit | Every layer's digest can change |
| `scripts/build.sh` with Podman 5.6 or later | Same as a release build |
| `scripts/build.sh` with an older Podman server | The script leaves the options out and prints a warning. The image works the same, but every layer gets a new digest. |

`/etc/agentainer/versions.json` in the image lists every pin and every installed apt package version.

## Agents do not update themselves

| Agent | Setting |
|---|---|
| Claude Code | `DISABLE_UPDATES=1` ([env vars](https://code.claude.com/docs/en/env-vars)) |
| Codex | `/etc/codex/requirements.toml` ([managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)) |
| Antigravity | `AGY_CLI_DISABLE_AUTO_UPDATE=true` ([troubleshooting](https://antigravity.google/docs/cli/troubleshooting.md)) |
| OpenCode | `"update": "disable"` in its global config, `~/.config/opencode/opencode.json` ([config](https://opencode.ai/v2/docs/config); OpenCode ignores the setting in project config). The image also sets `OPENCODE_DISABLE_AUTOUPDATE=1`, which OpenCode's [v1 CLI docs](https://opencode.ai/docs/cli/) name; the v2 docs do not, and whether 2.2.5 honors it is not verified. |

New versions arrive only with a new image.

## Scheduled updates

On the 1st and 15th of each month at 06:00 UTC, [`.github/workflows/bump.yml`](../.github/workflows/bump.yml) resolves the newest upstream versions with [`scripts/bump_versions.py`](../scripts/bump_versions.py) and opens a pull request against `develop`. It refuses to write any value that does not match the expected format for its pin. The pull request's build page shows which pins changed. A maintainer reviews and merges it by hand, and nothing is published until the next release.

An update PR lists increases to the leading number of a three-part tool version under "Major-version upgrades" and asks the maintainer to acknowledge the compatibility review in its description. CI does not enforce that checkbox. Minor updates to tools below 1.0 can also break compatibility, so review their upstream notes as well ([Semantic Versioning](https://semver.org/)).

The resolver follows current upstream release pointers with no minimum release age. Proposed binaries run in build and test jobs before anyone reviews the pull request. Checksums and publisher signatures establish byte identity and the signing identity, not that the code is safe, so review upstream changes before merging.

Run the same workflow manually through its `workflow_dispatch` trigger for an urgent security fix or an upstream change that breaks an agent. GitHub documents [scheduled](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) and [manual](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch) triggers.

The workflow opens the pull request with a GitHub App token when the repository has both the variable `BUMP_APP_CLIENT_ID` and the secret `BUMP_APP_PRIVATE_KEY`; CI then starts on its own. Otherwise it uses `GITHUB_TOKEN`, and GitHub holds the pull request's CI until a maintainer chooses "Approve workflows to run" ([CONTRIBUTING.md](../CONTRIBUTING.md#the-bump-github-app) describes the App).

## Releases

Releases use [Semantic Versioning](https://semver.org/):

- Stable versions have the form `MAJOR.MINOR.PATCH`, such as `0.1.0`.
- Development prereleases use the next intended version followed by `-dev.YYYYMMDD.N`, such as `0.1.0-dev.20261019.1`. The date must exist, and the build number starts at 1 and increments for another build that day.
- The parser also accepts other SemVer prerelease identifiers, such as `0.1.0-rc.1`.
- Container tags exclude SemVer build metadata (`+...`) and are limited to 128 characters ([distribution tag format](https://github.com/distribution/reference/blob/main/regexp.go)).

Versions below `1.0.0` are initial development, without a stable compatibility promise. Agentainer's public interfaces are its launcher commands, documented environment variables, configuration paths and persistent-home upgrade behavior. Bundled tool versions remain separate in `versions.env`.

Each release publishes `ghcr.io/chadmayfield/agentainer` for amd64 and arm64:

- tagged with the version and `sha-<commit>`, with `latest` reserved for stable releases;
- signed with cosign keyless signing, the index and each architecture's image;
- with an SBOM and BuildKit provenance for each architecture, a signed GitHub provenance attestation for the multi-architecture index, and zstd-compressed layers.

A release requires a maintainer-signed tag on a release merge in `main`; a branch merge alone does not publish. [CONTRIBUTING.md](../CONTRIBUTING.md#releases) describes the release procedure, the checks before publication and how `latest` moves.

Pull an explicit version tag. Prereleases never move `latest`, so before the first stable release there is no `latest` tag:

```sh
podman pull ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261024.1
AGENTAINER_IMAGE=ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261024.1 bin/agentainer up
```

A version exists only after its release workflow completes. A merge to `develop` runs CI and does not publish an image. To use features merged after the newest release tag, build the image locally with `scripts/build.sh`.

A runtime needs zstd support to pull the image:

| Runtime | First version that pulls zstd layers |
|---|---|
| Docker Engine | 23.0.0 ("Add support for pulling `zstd` compressed layers", [Engine 23.0 release notes](https://docs.docker.com/engine/release-notes/23.0/), moby/moby#41759) |
| containerd, including Kubernetes nodes that use it | 1.5.0 ("Add support for layers compressed with zstd", [containerd v1.5.0 release notes](https://github.com/containerd/containerd/releases/tag/v1.5.0)) |
| Podman | Not verified. Podman's release notes do not name a version. containers/image added zstd in containers/image#639, and Podman 1.6.2 is the first release whose `go.mod` uses a containers/image version with that change. |

The [release workflow for `v0.1.0-dev.20261019.1`](https://github.com/chadmayfield/agentainer/actions/runs/39373669375) completed signing, attestation storage and registry verification. Each later release must pass the same checks for its own digest.

## Verifying a release before use

Use a trusted checkout of this repository and independently installed Docker Buildx, cosign and GitHub CLI. Verify the maintainer-signed release tag with the trusted public key and fingerprint first. Obtain the full source commit from that tag and the image index digest from the registry. Review the digest before running the verifier; never substitute an unverified mutable tag afterward.

```sh
set -eu
version=0.1.0-dev.20261024.1
git verify-tag "v$version"
commit=$(git rev-parse "v$version^{commit}")
# Replace this placeholder with the release's full index digest.
digest=sha256:REPLACE_WITH_64_HEX_DIGITS
python3 tests/host/test-published-image.py ghcr.io/chadmayfield/agentainer "$digest" \
  "https://github.com/chadmayfield/agentainer/.github/workflows/build.yml@refs/tags/v$version" \
  https://token.actions.githubusercontent.com chadmayfield/agentainer "$commit" "refs/tags/v$version"
AGENTAINER_IMAGE="ghcr.io/chadmayfield/agentainer@$digest" bin/agentainer up
```

The verifier checks:

- Index and platform signatures against the exact workflow identity for the release tag and the GitHub OIDC issuer ([Sigstore CI verification](https://docs.sigstore.dev/quickstart/quickstart-ci/)).
- GitHub provenance against the repository, source commit, tag ref and workflow identity, rejecting self-hosted runners ([GitHub verification flags](https://cli.github.com/manual/gh_attestation_verify)).
- Both platforms' BuildKit provenance against the expected source repository and commit. A dirty or different revision fails ([BuildKit provenance fields](https://docs.docker.com/build/metadata/attestations/slsa-provenance/)).
- SBOM and provenance descriptors bound to each platform manifest, then a pull and native startup by the verified index digest ([attestation storage](https://docs.docker.com/build/metadata/attestations/attestation-storage/)).

It pulls and starts the verified digest, so run it only where you intend to run that release. It needs registry access and GitHub authentication. It does not establish a SLSA level or validate every SBOM package entry. Its commands and flags are in the [verifier source](../tests/host/test-published-image.py). The launcher does not perform these checks.

## Upstream publisher verification

The updater requires `gh`, `cosign` and GnuPG in addition to Python. The scheduled workflow installs cosign through its pinned installer action. [`scripts/verify_upstream.py`](../scripts/verify_upstream.py) checks supported publishers before the resolver writes any pins. A missing verification tool, missing signing asset, changed checksum or failed signature stops the update. Build downloads still check their pinned hashes.

| Download | Required publisher check |
|---|---|
| GitHub CLI | GitHub provenance from `cli/cli`, workflow `deployment.yml` on `refs/heads/trunk`. |
| uv | GitHub provenance from `astral-sh/uv`, workflow `release.yml` on `refs/heads/main`. |
| Ruff | GitHub provenance from `astral-sh/ruff`, workflow `release.yml` on `refs/heads/main`. |
| golangci-lint | GitHub provenance from `golangci/golangci-lint`, workflow `release.yml` at the selected release tag. |
| yq | Signed BSD checksum list from `mikefarah/yq`, workflow `release.yml` at the selected release tag. |
| Trivy binary | Signed checksum list from `aquasecurity/trivy`, workflow `reusable-release.yaml` at the selected release tag. |
| Codex package | Sigstore bundle for the whole package from `openai/codex`, workflow `rust-release.yml` at the selected release tag. |
| Claude Code | GPG-signed release manifest with the pinned Anthropic key fingerprint. |
| Node.js | GPG-signed `SHASUMS256.txt` by one of the release keys in `scripts/keys/nodejs-release-keys.asc`. |

GitHub provenance checks require the exact workflow certificate identity, repository, source ref and GitHub OIDC issuer ([GitHub CLI verification](https://cli.github.com/manual/gh_attestation_verify), [CLI release workflow](https://github.com/cli/cli/blob/trunk/.github/workflows/deployment.yml), [uv release workflow](https://github.com/astral-sh/uv/blob/main/.github/workflows/release.yml), [Ruff release workflow](https://github.com/astral-sh/ruff/blob/main/.github/workflows/release.yml), [golangci-lint release workflow](https://github.com/golangci/golangci-lint/blob/main/.github/workflows/release.yml)). Sigstore bundle checks require the exact workflow certificate identity and GitHub OIDC issuer ([cosign blob verification](https://docs.sigstore.dev/cosign/verifying/verify_blob/), [yq signing workflow](https://github.com/mikefarah/yq/blob/master/.github/workflows/release.yml), [Trivy signing workflow](https://github.com/aquasecurity/trivy/blob/main/.github/workflows/reusable-release.yaml), [Codex signing action](https://github.com/openai/codex/blob/main/.github/actions/linux-code-sign/action.yml)).

The updater does not check publisher signatures for Go, Rust, abtop, tea, kubectl, Helm, Antigravity, OpenCode or the pinned container images. Their checksum, package-manager and digest checks remain. Some of these projects publish signing material; their trust policies need separate review before the updater enforces them. No unsigned-update fallback exists for the publishers in the table.

### Node.js release keyring

The updater takes the newest stable `v26.x.y` from `https://nodejs.org/dist/index.json`. It checks that version's `SHASUMS256.txt.sig` with `gpg` against the keyring in [`scripts/keys/nodejs-release-keys.asc`](../scripts/keys/nodejs-release-keys.asc). A signature from any one of the eight active releasers' keys passes. The updater then reads the two Linux checksums from the verified file.

A failed Node.js check stops the whole scheduled update. `main()` in [`scripts/bump_versions.py`](../scripts/bump_versions.py) returns 1 on any `LookupFailed` and writes no pins, for every tool. This happens when the key that signed the release has expired or been revoked (`EXPKEYSIG` or `REVKEYSIG` in GnuPG's status output, with the message "the pinned signing key needs a hand update") and when a release is signed by a key that is not in the keyring. Updates for all tools resume only after a maintainer refreshes the keyring by hand.

The keyring comes from [`nodejs/release-keys`](https://github.com/nodejs/release-keys/tree/481637f813e912c4aa3622d7964ab426c97b8e8d), at commit `481637f813e912c4aa3622d7964ab426c97b8e8d`. Node.js lists the active releasers in its [release keys section](https://github.com/nodejs/node#release-keys). The scheduled update never changes these files. Refresh the keyring in its own pull request:

1. At the new `nodejs/release-keys` commit, take the fingerprints listed between the `<!-- Active releasers keys -->` markers in its README.
2. Download each `keys/<FINGERPRINT>.asc` at that commit.
3. Import the files into a temporary `GNUPGHOME`.
4. Write `scripts/keys/nodejs-release-keys.asc` with `gpg --armor --export <the fingerprints>`. Do not concatenate the downloaded files. At least one of them has no trailing newline, and plain concatenation silently drops a key.
5. Set `NODE_KEY_FINGERPRINTS` and the commit in its comment in `scripts/bump_versions.py`.
6. Update the commit and the expiry dates in this section.
7. Run the unit tests. `test_node_keyring_holds_exactly_the_pinned_fingerprints` checks the keyring file against the constant.

Expiry dates of the eight keys in the current keyring, read with `gpg --list-keys` from a temporary `GNUPGHOME`:

| Releaser | Expires |
|---|---|
| Rafael Gonzaga | 2027-06-04 (primary key) |
| Ulises Gascón | 2027-07-18 (signing subkey); 2028-06-01 (primary key) |
| Stewart X Addison | 2028-06-28 |
| Marco Ippolito | 2034-03-26 |
| Ruy Adorno | none |
| Antoine du Hamel | none |
| Richard Lau | none |
| Juan José Arboleda | none |

Refresh the keyring before the earliest date.
