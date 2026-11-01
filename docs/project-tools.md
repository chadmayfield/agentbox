# Project-local tooling

Run these commands inside Agentainer, from the project root under `/workspace`. Follow an existing project's dependency files, lockfile and setup instructions. Each new-project example below assumes its own empty directory.

The image supplies Python, uv, Node.js and npm. The examples install development dependencies into the project. They do not change Agentainer's image pins or require sudo. Initial package resolution and uncached downloads need network access ([uv projects](https://docs.astral.sh/uv/guides/projects/), [npm install](https://docs.npmjs.com/cli/v9/commands/npm-install/)).

## Contents

- [Python tests and linting with uv](#python-tests-and-linting-with-uv)
- [JavaScript dependencies and package-manager versions](#javascript-dependencies-and-package-manager-versions)
- [Language servers](#language-servers)
- [Browser tests](#browser-tests)
- [Native builds](#native-builds)
- [PostgreSQL scripts](#postgresql-scripts)
- [Kubernetes and Helm clients](#kubernetes-and-helm-clients)
- [Persistence](#persistence)

## Python tests and linting with uv

For a new Python project, create its dependency declaration and add pytest and Ruff to the development group:

```sh
uv init --bare --vcs none
uv add --dev pytest ruff
mkdir -p tests
cat > tests/test_example.py <<'PY'
def test_addition():
    assert 2 + 2 == 4
PY
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

`uv add` updates `pyproject.toml` and resolves exact versions in `uv.lock`. The project environment is `.venv`. Keep `pyproject.toml` and `uv.lock` in version control; leave `.venv` out. See [dependency management](https://docs.astral.sh/uv/guides/projects/#managing-dependencies) and [Ruff's tutorial](https://docs.astral.sh/ruff/tutorial/).

For an existing uv project that declares pytest and Ruff, install its locked dependencies and run its checks:

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

`--locked` rejects a missing or stale lockfile instead of updating it. It does not force offline operation. Use `uv add` when deliberately changing dependencies, then review the declaration and lockfile together ([locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)).

The example uses the image's Python. An existing project can require a different Python version; follow its runtime requirements. Ubuntu's Python rejects global and `--user` pip installs outside a virtual environment, so use the project's uv workflow or venv ([Python packaging and tool persistence](configuration.md#tools-that-agents-install)).

## JavaScript dependencies and package-manager versions

For a new npm project, record the npm version in use, add TypeScript as an exact development dependency, and create a test with Node's built-in test runner:

```sh
npm init --yes
npm pkg set "packageManager=npm@$(npm --version)" 'scripts.test=node --test'
npm install --save-dev --save-exact typescript
mkdir -p tests
cat > tests/example.test.mjs <<'JS'
import assert from 'node:assert/strict';
import test from 'node:test';

test('addition', () => {
  assert.equal(2 + 2, 4);
});
JS
npm exec -- tsc --version
npm test
```

Keep `package.json`, `package-lock.json` and the tests in version control; leave `node_modules` out. `--save-exact` records the selected dependency version without a range. `npm exec` runs the local TypeScript compiler in this example. See [npm install](https://docs.npmjs.com/cli/v9/commands/npm-install/), [npm pkg](https://docs.npmjs.com/cli/v9/commands/npm-pkg/) and [Node's test runner](https://github.com/nodejs/node/blob/v26.x/doc/api/test.md).

For an existing npm project with a committed lockfile and a test script:

```sh
npm ci
npm test
```

`npm ci` requires the lockfile to agree with `package.json`, replaces `node_modules` and leaves the dependency declarations and lockfile unchanged. Use `npm install` for deliberate dependency changes. Keep any project-specific install flags in the project's configuration so local and CI installs agree ([npm ci](https://docs.npmjs.com/cli/v9/commands/npm-ci/)).

The `packageManager` field records the project's expected package-manager version. Running plain `npm` uses the executable on `PATH`; the field alone does not switch it. Check `npm --version` against the project's requirement. The Corepack README says Node.js distributed Corepack "up to (but not including) 25.0.0" ([Corepack README](https://github.com/nodejs/corepack#readme)). The image's Node.js 26 does not include it. `tar -tf node-v26.13.0-linux-x64.tar.xz` lists no corepack entry. To use pnpm or Yarn, install it the way the project documents. Alternatively, run `npm install -g corepack` and then `corepack enable` (same README). Follow an existing pnpm or Yarn project's setup rather than creating an npm lockfile beside its own lockfile.

## Language servers

See [optional language tooling](language-tooling.md) for gopls, rust-analyzer, Pyright and TypeScript 7's native server, with a project-local TypeScript 6 fallback. Installing a server does not configure an editor or agent to use it.

## Browser tests

See [optional browser testing](browser-testing.md) for project-local Playwright installation, Linux dependencies, persistent browser downloads and a headless execution check. Browsers are installed only when you choose that setup.

## Native builds

The image includes GCC, G++, Make, CMake, Ninja and pkg-config. For an existing CMake project that supports Ninja:

```sh
cmake -S . -B build -G Ninja
cmake --build build
```

`-S` selects the source directory and `-B` keeps generated files in a separate build directory. `-G Ninja` selects the Ninja generator. See the [CMake command reference](https://cmake.org/cmake/help/latest/manual/cmake.1.html) and [Ninja manual](https://ninja-build.org/manual.html).

Native addons build through `node-gyp`, which downloads the development files (headers) for the target Node.js version. `--devdir` sets the download directory, and the default is the OS cache directory. `--tarball` takes the headers from a local tarball ([node-gyp README](https://github.com/nodejs/node-gyp#readme)). That README does not say when the download happens or how to build offline with the image's Node.js; not verified.

pkg-config reads installed `.pc` metadata to supply compiler and linker flags. It does not install libraries. Project-specific headers and libraries remain optional dependencies; follow the project's setup instructions. See [Ubuntu's pkg-config manual](https://manpages.ubuntu.com/manpages/resolute/man1/pkg-config.1.html). The package list is [`build/apt-packages.txt`](../build/apt-packages.txt); the existing `APT_SNAPSHOT` pin in [`versions.env`](../versions.env) selects their versions.

## PostgreSQL scripts

Use `pgcli` for interactive work and `psql` for scripts. The image includes the client, not a PostgreSQL server. Configure the connection using your project's runtime environment or PostgreSQL service file. Supply credentials at runtime through a protected password file, never in a command-line connection URL. See [connection environment variables](https://www.postgresql.org/docs/current/libpq-envars.html), [service files](https://www.postgresql.org/docs/current/libpq-pgservice.html) and [password files](https://www.postgresql.org/docs/current/libpq-pgpass.html).

Run a project's SQL file after configuring its connection:

```sh
psql --no-psqlrc --no-password --set ON_ERROR_STOP=1 --file ./migration.sql
```

`--no-psqlrc` skips startup customizations. `--no-password` prevents an unattended script from waiting for a password prompt. `ON_ERROR_STOP=1` stops on SQL errors and returns exit code 3; connection failures return 2. Check the exit code in automation. Stopping does not undo earlier committed statements. Follow the project's transaction strategy. See the [psql reference](https://www.postgresql.org/docs/current/app-psql.html).

## Kubernetes and Helm clients

The image includes pinned `kubectl` and Helm release binaries for amd64 and arm64. Their versions and the projects' published SHA-256 checksums live in [`versions.env`](../versions.env). Each tool has its own build stage; the scheduled version updater resolves its stable release and both checksums. See [kubectl binary installation](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/) and [Helm binary installation](https://helm.sh/docs/intro/install/#from-the-binary-releases).

Inspect client versions without contacting a cluster:

```sh
kubectl version --client=true --output=json
helm version --short
```

Local rendering also works without a cluster:

```sh
kubectl kustomize ./deploy/kubernetes
helm template example-release ./path/to/chart
```

`kubectl kustomize` reads the local kustomization, and `helm template` renders the local chart. Remote bases, chart dependencies or template options can introduce downloads or cluster access; follow the project's instructions. Agentainer's tests use local fixtures with networking disabled and no kubeconfig. See [kubectl kustomize](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_kustomize/) and [Helm template](https://helm.sh/docs/helm/helm_template/).

Cluster credentials are not included. Supply a kubeconfig at runtime only when you intend to allow cluster access, and check that kubectl is within one minor version of the API server ([kubectl version skew](https://kubernetes.io/releases/version-skew-policy/#kubectl)). Cloud authentication helpers and cloud CLIs are not bundled. Helm 4 is the current stable major selected by the upstream release API; projects requiring Helm 3 must use a compatible custom setup ([Helm releases](https://github.com/helm/helm/releases)).

## Persistence

`.venv` and `node_modules` live with the project under the workspace mount. `AGENTAINER_TOOLS=persist` controls supported user-wide tool installations separately. See [customization](customization.md#project-dependencies-and-installed-tools) for recreation and runtime-change guidance. A persistent home does not preserve dependencies installed only in a container's writable layer.
