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
  - [AWS CLI signing key](#aws-cli-signing-key)
- [Optional extras](#optional-extras)
  - [npm registry keys](#npm-registry-keys)

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

`versions.env` also pins the [optional extras](extras.md), which the image carries as lockfiles but does not install ([Optional extras](#optional-extras)).

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

The resolver follows current upstream release pointers with no minimum release age, except for the optional extras ([Optional extras](#optional-extras)). Proposed binaries run in build and test jobs before anyone reviews the pull request. Checksums and publisher signatures establish byte identity and the signing identity, not that the code is safe, so review upstream changes before merging.

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

The updater requires `gh`, `cosign` and GnuPG in addition to Python. The scheduled workflow installs cosign through its pinned installer action. [`scripts/verify_upstream.py`](../scripts/verify_upstream.py) checks supported publishers before the resolver writes any pins. A missing verification tool, missing signing asset, changed checksum or failed signature stops the update. Build downloads still check their pinned hashes. The optional extras are the exception: a failed check keeps only that extra's pin ([Optional extras](#optional-extras)).

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
| AWS CLI | GPG signature (`<zip>.sig`) on each installer zip, by the AWS CLI Team key in `scripts/keys/aws-cli-public-key.asc` with the fingerprint pinned in the updater. AWS publishes no checksums, so the updater computes the SHA-256 pins from the verified zips. |
| Optional extras (npm) | npm registry signature on every lockfile entry, by a key in `scripts/keys/npm-registry-keys.json` ([Optional extras](#optional-extras)). |

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

### AWS CLI signing key

The updater takes the first version heading of the AWS CLI v2 changelog, `https://raw.githubusercontent.com/aws/aws-cli/v2/CHANGELOG.rst`, which AWS links as the list of versions ([installing past releases](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-version.html)). For each architecture it downloads `awscli-exe-linux-<x86_64|aarch64>-<version>.zip` and its `.sig` from `https://awscli.amazonaws.com` and checks the signature with `gpg` against [`scripts/keys/aws-cli-public-key.asc`](../scripts/keys/aws-cli-public-key.asc). AWS publishes no checksum for the zips, so the updater computes the SHA-256 pins only after both signatures pass. When the newest version equals `AWSCLI_VERSION`, the updater downloads nothing and keeps the pins.

A failed AWS CLI check stops the whole scheduled update. `main()` returns 1 and writes no pins, for every tool, as for Node.js.

AWS publishes the key as text in the [AWS CLI install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), not as a file to download. The file is a copy of that block. The guide lists the key as `AWS CLI Team <aws-cli@amazon.com>`, fingerprint `FB5D B77F D5C1 18B8 0511 ADA8 A631 0ACC 4672 475C`, expiring 2027-07-01. `test_aws_cli_key_holds_exactly_the_pinned_fingerprint` checks the file against `AWSCLI_KEY_FINGERPRINT` in `scripts/bump_versions.py`.

After 2027-07-01, GnuPG reports `EXPKEYSIG` for a release signed with this key, with the message "the pinned signing key needs a hand update". The signature check fails and the scheduled update stops for all tools until a maintainer refreshes `scripts/keys/aws-cli-public-key.asc` from the install guide. To refresh it, copy the key block from the guide into the file, set `AWSCLI_KEY_FINGERPRINT` if the fingerprint changed, update the expiry date here, and run the unit tests.

Refresh the key before 2027-07-01.

## Optional extras

`versions.env` pins three npm tools that `agentainer-extras install` adds on request ([Optional extras](extras.md)):

| Pin | npm package | Catalog directory |
|---|---|---|
| `KANDEV_VERSION` | [`kandev`](https://registry.npmjs.org/kandev) | `kandev` |
| `OPENCHAMBER_VERSION` | [`@openchamber/web`](https://registry.npmjs.org/@openchamber/web) | `openchamber` |
| `REA_VERSION` | [`rea-agents`](https://registry.npmjs.org/rea-agents) | `rea` |

Each catalog directory, under `rootfs/usr/local/share/agentainer/extras/`, holds a `package.json` that depends on exactly the pinned version and a `package-lock.json` with an `integrity` hash for every package in the tree. The version in `package.json` must equal the `versions.env` pin, and `tests/host/test-extras-catalog.sh` checks this in CI.

For each extra, [`scripts/bump_versions.py`](../scripts/bump_versions.py):

1. Picks the newest stable, non-deprecated version, no newer than the `latest` dist-tag, whose publish time in the registry's `time` field is at least 7 days old. When that version is not newer than the pin, the pin and the catalog files stay as they are.
2. Regenerates the lockfile with `npm install --package-lock-only --ignore-scripts --before=<now minus 7 days>`, so every dependency in the tree is also at least 7 days old ([npm `before`](https://docs.npmjs.com/cli/v11/using-npm/config#before)). It uses an empty npm user config and the public registry.
3. Fails the extra when the new lockfile has a package with an install script (`hasInstallScript`, [package-lock.json](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json)) that the committed lockfile did not have, unless the package is `node-pty` or `frida`. `agentainer-extras` installs with `--ignore-scripts`, so no install script runs; this check reports a change in the tree for review.
4. Checks every lockfile entry against the registry. The entry must resolve from `https://registry.npmjs.org/`, its `integrity` must equal the registry's `dist.integrity` for that version, and one of the version's `dist.signatures` must verify with `openssl` over `<name>@<version>:<integrity>` with an ECDSA P-256 key in `scripts/keys/npm-registry-keys.json` ([npm registry signatures](https://docs.npmjs.com/about-registry-signatures)). A key with an `expires` time counts only for a version published before that time. A signature by an unknown key does not count. Bundled entries are covered by their parent's integrity; a `link` entry fails.

A failed check for one extra, including a missing `npm` or `openssl`, keeps that extra's pin and catalog files and does not stop the run. The other pins still update. `bump_versions.py --failures FILE` writes one line per failed extra to FILE. In the scheduled workflow, the `extras-failures` job prints those lines in the run summary and fails the run after the pull request for the other pins is open.

The pull request job applies the resolver's patch only when it modifies `versions.env`, `deploy/kubernetes/*/deployment.yaml` or an extras `package.json` or `package-lock.json`, and creates, deletes or renames no file ([`.github/actions/bump-pr/action.yml`](../.github/actions/bump-pr/action.yml)).

CI's `lint-unit` job runs `tests/host/test-extras-catalog.sh` and scans the extras lockfiles with Trivy, using the `TRIVY_SCANNER_IMAGE` pin. The scan is report only: findings go to the job's step summary and never fail the job.

### npm registry keys

[`scripts/keys/npm-registry-keys.json`](../scripts/keys/npm-registry-keys.json) is a copy of `https://registry.npmjs.org/-/npm/v1/keys`. It holds two keys: `SHA256:jl3bwswu80PjjokCgh0o2w5c2U4LhQAE57gj9cz1kzA`, which expired on 2025-01-29, and `SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U`, with no expiry. The scheduled update never changes this file. A signature by a key that is not in the file fails that extra's update until a maintainer refreshes the file in its own pull request:

1. Download `https://registry.npmjs.org/-/npm/v1/keys`.
2. Replace `scripts/keys/npm-registry-keys.json` with the downloaded document, unchanged. Every key must have `keytype` and `scheme` `ecdsa-sha2-nistp256`; `bump_versions.py` refuses any other.
3. Update the date in the comment above `NPM_KEYS` in `scripts/bump_versions.py` and the key list in this section.
4. Update the key IDs and expiry times in `test_registry_keys_file_pins_both_npm_keys` in `tests/unit/test_bump_versions.py`, then run the unit tests.
