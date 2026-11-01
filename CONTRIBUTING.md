# Contributing

This file covers how to work on Agentainer. The rules every change follows, for people and AI coding agents alike, are in [AGENTS.md](AGENTS.md).

## Branches

The repo uses git-flow:

- `develop` is the default branch. Open pull requests against it.
- Work on a `feature/<name>` branch made from `develop` (`git flow feature start <name>`, or `git switch -c feature/<name> develop`).
- `main` holds releases and changes only through release pull requests.
- Merged branches are deleted automatically. Merge with "Create a merge commit"; squash and rebase merges are turned off. These are repository settings in GitHub, not files in this repository.

## Build and test

You need Podman or Docker.

```sh
scripts/build.sh                            # builds localhost/agentainer:dev for your architecture
sh tests/run.sh                             # container tests against that image
sh tests/lint.sh                            # shellcheck, shfmt and Ruff, run from the image
python3 -m unittest discover -s tests/unit  # unit tests, no container needed
sh tests/14-unit-linux.sh                   # image Python and Linux-only unit modules
sh tests/host/test-launcher.sh              # launcher tests, no container needed
sh tests/host/test-build-script.sh          # scripts/build.sh tests, no container needed
sh tests/host/test-fetch.sh                 # fetch.sh and Rust manifest check tests, no container needed
sh tests/host/test-manifests.sh             # Kubernetes manifest tests (kubectl, and the image for yq)
sh tests/host/test-launcher-integration.sh  # real engine, existing local image
sh tests/host/test-build-uid.sh             # slow: builds a full image with --uid 1001 --gid 20
python3 tests/host/test-layer-repro.py      # slow: two clean tool builds, configured Buildx
python3 tests/host/test-healthcheck.py      # also invoked by tests/58-healthcheck.sh
python3 tests/host/test-language-tooling.py --image localhost/agentainer:dev  # slow, network
python3 tests/host/test-playwright-setup.py --image localhost/agentainer:dev  # slow, network
# Release verification arguments: docs/versions.md#verifying-a-release-before-use
# Optional terminal screenshots: tests/visual/README.md
```

With Docker, prefix the commands with `RUNTIME=docker`. `IMAGE=<name>` tests another image. Two tests do not follow both settings:

- `tests/host/test-layer-repro.py` always runs `docker buildx`.
- `tests/host/test-build-uid.sh` builds and tests its own image tag. On a build failure it prints the last 80 lines of the build output.

### Python linting

`sh tests/lint.sh` runs Ruff from the built image alongside shellcheck and shfmt. CI runs the same command in each architecture's image job. Rebuild the image after changing its Ruff pin. No host Ruff installation is required.

[`ruff.toml`](ruff.toml) selects only Pyflakes `F` rules. [`scripts/lint-python.py`](scripts/lint-python.py) includes `.py` files and Python shebang commands in the source directories, including `build/` and extensionless runtime commands. It excludes dependency and cache directories. Explicit file arguments prevent Ruff's default exclusion of `build/` from hiding those scripts ([Ruff file discovery](https://docs.astral.sh/ruff/configuration/#python-file-discovery), [Pyflakes rules](https://docs.astral.sh/ruff/rules/#pyflakes-f)).

### Kelos variant

[`Containerfile.kelos`](Containerfile.kelos) builds a variant image for Kelos on top of a published Agentainer image ([docs/kelos.md](docs/kelos.md)). Its files are in `rootfs-kelos/` and its tests in `tests/kelos/`.

```sh
scripts/build.sh --variant kelos [--from IMAGE]                       # builds localhost/agentainer-kelos:dev
IMAGE=localhost/agentainer-kelos:dev sh tests/kelos/test_image.sh     # tests for the variant
```

Without `--from`, the build uses the digest-pinned image named in `Containerfile.kelos`. The `kelos-capture` stage needs network access to github.com and the Go module proxy. CI does not build or test the variant.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every pull request, every push to `develop` and `main`, and every `v*` tag push. A pull request also runs it again when you edit it, which includes changing its base branch:

- the `lint-unit` job: actionlint, the Python unit tests, and the launcher, `scripts/build.sh` and `build/fetch.sh` tests;
- the `image` job, on amd64 and arm64: the image build, shellcheck and shfmt (`tests/lint.sh` runs them from the image), the container tests and real launcher lifecycle under Docker and rootless Podman, a custom UID/GID build, the manifest tests, and trivy scans (a secret fails the build; vulnerabilities are reported). On amd64 only, it also checks that the four agents and Node.js start on a CPU without AVX2.

The `layer-repro` job runs on amd64 and arm64 and uses the pinned BuildKit image to build an isolated copy of every tool twice with no cache. It compares the exported tool-layer digests. This checks unchanged inputs; it does not test every possible combination of pin changes. The required `ci` check includes this job.

The image and layer comparison jobs are skipped when every changed file is `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` or a file under `docs/` other than `docs/kubernetes.md` (the manifest tests check its install commands). For a pull request, the changed files are what the merge adds to the base branch. For a push to `develop`, they are the files changed since the previous tip. A push to `main` and a pull request whose base branch changed always build the image. A docs-only change gets no shell lint, because no shell file changed. The required check is `ci`, which passes only when every job passed or the image job was skipped for a docs-only change.

The manual [optional tooling workflow](.github/workflows/optional-tooling.yml) (`workflow_dispatch`) builds the selected source and runs the networked language-server and Playwright installation checks with Docker on amd64 and arm64 runners. It has read-only repository permission and is separate from the required `ci` check. Not verified: it has no runs yet (`gh run list --workflow optional-tooling.yml` returns none).

## Signing local commits

Configure signing once in your checkout, with your own full GPG fingerprint and a key whose UID uses your GitHub noreply address:

```sh
git config --local user.signingkey YOUR_FULL_GPG_FINGERPRINT
git config --local gpg.format openpgp
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

These settings stay in `.git/config`, apply to this local clone and its worktrees, and are not shared with contributors or other clones. Register the public key on your GitHub account so GitHub can verify signatures. Keep the private key on your signing host. A signing failure stops the commit; fix access to the key instead of disabling signing. Verify a new commit with `git verify-commit HEAD` ([Git configuration](https://git-scm.com/docs/git-config), [commit verification](https://git-scm.com/docs/git-verify-commit)). GitHub-generated merge commits and automated bump commits use their own identities.

## Releases

1. From an up-to-date `develop` whose CI passed, run `git flow release start <version>`. Use SemVer, such as `0.1.0`, or a dated development prerelease, such as `0.1.0-dev.20261019.1` ([version policy](docs/versions.md#releases)).
2. Push the branch and open a pull request from `release/<version>` to `main`.
3. When `ci` passes, merge with "Create a merge commit". The subject must be exactly `Merge pull request #N from <owner>/release/<version>`. A push to `main` tests the merge but does not publish.
4. Fetch the merged commit, create a signed annotated tag `v<version>` on that exact merge commit with `git tag -s v<version> <merge-commit> -m "Release v<version>"`, verify it with `git verify-tag v<version>`, then push only that tag with `git push origin refs/tags/v<version>` ([signed tags](https://git-scm.com/docs/git-tag)). Do not tag the release branch's pre-merge tip.
5. The tag push runs CI. After aggregate CI passes, `scripts/check_release_tag.py` requires a two-parent release merge on main's first-parent history, a matching tag version and target, and a valid GPG signature by the trusted primary key. It retrieves the owner's public key from GitHub and verifies in a temporary keyring. Set the repository Actions variable `RELEASE_SIGNING_FINGERPRINT` to that full uppercase fingerprint. The signing key must be registered on the repository owner's GitHub account, or on the account named by the optional `RELEASE_SIGNER` Actions variable for an organization-owned repository ([public GPG keys API](https://docs.github.com/en/rest/users/gpg-keys)). A missing key setting, unsigned tag or existing GitHub release stops publishing. The version job checks out `main` to run this check, so a candidate tag cannot replace it.
6. Approve the `authorize-release` job in the `release` environment. Then the workflow:
   1. Builds and pushes both architectures.
   2. On each native runner, pulls the pushed digest, checks the image architecture, source revision and release version, and starts the image and all four agent binaries before uploading its digest artifact ([platform check](scripts/check-release-platform.sh)). A failure stops index publication and promotion.
   3. Assembles an index tagged only `sha-<short>`, signs it and the platform manifests with cosign, and creates a GitHub provenance attestation for the index, stored in GitHub and GHCR.
   4. Runs [`tests/host/test-published-image.py`](tests/host/test-published-image.py): exact workflow identity, source commit and tag ref for GitHub provenance; expected repository and commit in each platform's BuildKit provenance; signatures, SBOM descriptors and native startup.
   5. Only after that verification, moves the version tag, and `latest` for the highest stable version (see [moving `latest`](#moving-latest)).
   6. Creates the GitHub release with `--verify-tag`, keeping the maintainer-signed tag. Prereleases are marked as prereleases and excluded from latest.
7. Open a pull request from `main` to `develop` to bring back fixes made on the release branch.

Do not run `git flow release finish`: it merges into `main` locally. A hotfix is a new release made the same way. A `hotfix/*` merge does not authorize publication.

Re-run a failed tag workflow without replacing the signed tag. A failure before verification and the retag dry run pass leaves the version and `latest` tags unchanged. A rebuilt image gets a new digest; it must be signed, attested and verified again before promotion. Once the GitHub release exists, its version cannot be republished. Use a new version for further changes.

CI holds no maintainer private signing key. It verifies the GPG-signed release tag using the maintainer's public key, then uses GitHub OIDC for container image signatures and attestations.

The published image is a fresh build from the release commit with the same pinned inputs, not the exact image the pull request's tests ran on. The verifier checks the named fields; it does not establish a SLSA level or validate every SBOM package entry. Fixtures exercise rejection cases in pull requests.

### Moving latest

The release job refreshes `main` while holding its release lock. Only the highest stable SemVer in main's first-parent release merges can move `latest`. Prereleases never move it, even when they target a higher version. A delayed older stable build or retry publishes its own version tag and leaves `latest` alone. Ordering is numeric, so `0.1.10` follows `0.1.2`, and `0.1.0-dev.20261019.10` follows `0.1.0-dev.20261019.2`. A version without a prerelease suffix follows every prerelease of that same version ([release script](scripts/release-image.sh), [version comparison](scripts/release_order.py)). GitHub releases use the same decision ([GitHub CLI release flags](https://cli.github.com/manual/gh_release_create)).

### Release concurrency

The release job's concurrency group keeps one running job and one pending job. Under GitHub's default policy, a third queued release replaces the pending one. Check all pushed tags and rerun any canceled release workflow ([concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)). GitHub documents larger queues; whether the pinned actionlint accepts that setting is not verified.

### GitHub release controls

These controls are GitHub repository settings. The workflow files cannot enforce them, so an administrator must configure them:

- The `release` environment requires the maintainer's approval and permits only `v*` tags. Self-approval is allowed so a sole maintainer can release. The `authorize-release` job waits for that approval before the publish jobs run ([environment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)).
- A tag ruleset blocks updates and deletion of `v*` tags, without bypass actors, and permits new tags. Correct a released version by creating a new version instead of replacing its tag ([ruleset rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)).
- Protect `main` and release-tag creation.
- Fork pull-request workflows require approval for all external contributors. Review their changes before approving a run ([fork workflow approval](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)).

## The bump GitHub App

The scheduled update ([`.github/workflows/bump.yml`](.github/workflows/bump.yml)) opens its pull request with a GitHub App token, so CI starts without "Approve workflows to run". To set the App up:

1. Under your account's Settings, Developer settings, GitHub Apps, create a new App. Use the repository URL as its homepage and turn off its webhook.
2. Give it the repository permissions Contents (read and write) and Pull requests (read and write), and nothing else. Allow installing it only on your account.
3. Copy its Client ID (not the App ID) and generate a private key.
4. Install the App on the `agentainer` repository only.
5. In the repository's Settings, Secrets and variables, Actions, add the variable `BUMP_APP_CLIENT_ID` (the Client ID) and the secret `BUMP_APP_PRIVATE_KEY` (the whole `.pem` file). Then delete the downloaded key file.
6. Run `gh workflow run bump.yml`. If it opens a pull request, its CI starts on its own, and the commit author is the App's bot user.

The workflow uses the App only when both the variable and the secret are set. If either is missing, it uses `GITHUB_TOKEN`. With both set, wrong App credentials fail the App job without falling back; remove the variable or the secret to go back to `GITHUB_TOKEN`.

## Security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).
