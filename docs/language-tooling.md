# Optional language tooling

Language servers provide navigation, completion and diagnostics through an editor or agent's LSP client. Installing a server does not configure a client. Agentainer's seeded Vim configuration does not install an LSP plugin. Follow your client's setup instructions and the project's runtime requirements ([Language Server Protocol](https://microsoft.github.io/language-server-protocol/), [Vim defaults](defaults.md#vim-and-editorconfig)).

These are optional user installations. They do not change the image's pins or install anything at startup. Initial installation needs network access. The examples use the bundled Go, Rust and Node.js runtimes, and run as `agent` without sudo.

## Contents

- [Preserve user-installed tools](#preserve-user-installed-tools)
- [Go with gopls](#go-with-gopls)
- [Python with Pyright](#python-with-pyright)
- [TypeScript 7 with its native server](#typescript-7-with-its-native-server)
  - [TypeScript 6 compatibility fallback](#typescript-6-compatibility-fallback)
- [Rust with rust-analyzer](#rust-with-rust-analyzer)
- [Updates and verification](#updates-and-verification)

## Preserve user-installed tools

With the default `ephemeral` tools mode, Go and npm commands you install are lost when the container is replaced. To keep them, set `AGENTAINER_TOOLS=persist` before you create the container ([tools that agents install](configuration.md#tools-that-agents-install)). The separate Rust home described below stays on the home volume in either mode.

## Go with gopls

Install the Go team's language server with the currently bundled compiler:

```sh
GOTOOLCHAIN=local go install golang.org/x/tools/gopls@latest
gopls version
```

`go install` compiles the selected module and installs its executable under the image's `GOBIN`, which is already on `PATH`. It does not add a dependency to the current project when a version suffix is supplied. `GOTOOLCHAIN=local` prevents an automatic Go compiler download. If a future gopls release requires newer Go, choose a compatible gopls release or a newer Agentainer image. See [gopls installation](https://go.dev/gopls/#installation), [go install](https://pkg.go.dev/cmd/go#hdr-Compile_and_install_packages_and_dependencies) and [Go toolchain selection](https://go.dev/doc/toolchain).

The image defaults to `GOTOOLCHAIN=local`. To let a project select and download newer Go toolchains, opt in for that command with `GOTOOLCHAIN=auto go test ./...`, or set `GOTOOLCHAIN=auto` in the container's runtime environment. Downloaded toolchains are not the image's pinned compiler ([Go toolchain selection](https://go.dev/doc/toolchain#select)).

Configure the client to launch `gopls serve`. Its Go environment must match the project's module and workspace setup. See [gopls editor configuration](https://go.dev/gopls/#editors).

## Python with Pyright

Install Microsoft's npm package, using the image's writable npm prefix ([tools that agents install](configuration.md#tools-that-agents-install)):

```sh
npm install --global pyright
pyright --version
```

Configure an LSP client to launch `pyright-langserver --stdio`. The `pyright` command is the batch type checker; it is not the LSP server command. The package supplies both executables ([installation](https://github.com/microsoft/pyright/blob/main/docs/installation.md), [package entrypoints](https://github.com/microsoft/pyright/blob/main/packages/pyright/package.json), [server transport](https://github.com/microsoft/pyright/blob/main/packages/pyright-internal/src/nodeServer.ts)).

Select the project's Python environment in your client and Pyright configuration. A user-wide server installation does not install the project's imports. See [Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md) and [Python project dependencies](project-tools.md#python-tests-and-linting-with-uv).

## TypeScript 7 with its native server

Install the native TypeScript compiler and language server:

```sh
npm install --global typescript@7
tsc --version
```

Configure the client to launch `tsc --lsp --stdio`. This uses TypeScript 7's native LSP implementation, without the separate `typescript-language-server` wrapper. Both flags are required by the native CLI ([TypeScript 7 announcement](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/), [CLI dispatch](https://github.com/microsoft/TypeScript/blob/main/tsc/cmd/tsc/main.go), [LSP transport](https://github.com/microsoft/TypeScript/blob/main/tsc/cmd/tsc/lsp.go)).

For a project-owned compiler version, install TypeScript as a development dependency using the project's package manager, then configure the client to launch that project's `node_modules/.bin/tsc --lsp --stdio`. An existing project-local `tsc` can take precedence in npm scripts. Follow the project's version declaration and lockfile instead of assuming it uses the user-wide installation.

### TypeScript 6 compatibility fallback

Microsoft identifies framework and plugin workflows that still need TypeScript 6, including embedded language tooling. Follow the framework's supported versions. The community `typescript-language-server` instructions currently select `typescript@6` ([Microsoft's compatibility notes](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/), [legacy server installation](https://github.com/typescript-language-server/typescript-language-server#installing)).

In a project that needs this fallback, use its package manager to install the legacy server and compatible compiler. For npm:

```sh
npm install --save-dev --save-exact typescript-language-server typescript@6
./node_modules/.bin/typescript-language-server --version
```

Configure the client to launch that project's `node_modules/.bin/typescript-language-server --stdio`. This keeps the TypeScript 6 dependency and server local to the project and leaves the user-wide TypeScript 7 installation in place. Keep the declaration and lockfile in version control. Do not replace an existing project's compiler version without checking its framework requirements.

## Rust with rust-analyzer

The image's `rust-analyzer` executable is a rustup proxy. Its presence on `PATH` does not mean the analyzer component is installed. Check `rust-analyzer --version`; the minimal image toolchain does not include that component ([rustup components](https://rust-lang.github.io/rustup/concepts/components.html), [image installation](../build/install-tool.sh)).

The bundled toolchain lives under `/opt/rustup`. For a persistent, user-owned installation, capture the currently selected compiler version before selecting a separate rustup home:

```sh
rust_version=$(rustc --version | awk '{print $2}')
export RUSTUP_HOME="$HOME/.agentainer/rustup"
rustup toolchain install "$rust_version" --profile minimal \
  --component rust-analyzer,rust-src --default --no-self-update
rust-analyzer --version
```

This downloads another toolchain with its analyzer and standard-library sources into the home volume. It does not modify `/opt/rustup` and does not require sudo. `--default` selects that compiler in the new rustup home; project overrides still apply. See [rustup environment variables](https://rust-lang.github.io/rustup/environment-variables.html), [rust-analyzer installation](https://rust-analyzer.github.io/book/rust_analyzer_binary.html#rustup) and [standard-library sources](https://rust-analyzer.github.io/book/installation.html#rust-standard-library). The install flags were checked with the bundled `rustup toolchain install --help`.

Export the same `RUSTUP_HOME` in each session that uses these tools, or add the export to your own container `~/.bashrc`. An LSP client started outside that shell also needs the variable. Configure the client to launch `rust-analyzer`. Keep the server, compiler and `rust-src` compatible with the project; repeat the component installation when selecting another toolchain.

## Updates and verification

The examples select current upstream releases at installation time. Record `gopls version`, `npm list --global --depth=0` and `rust-analyzer --version` with your setup instructions. Select explicit upstream versions when reproducing an installation. The scheduled Agentainer version bump does not update these user-installed tools.

After an image architecture or runtime change, validate or reinstall persisted tools. `agentainer-tools reset` moves all persisted tool roots aside, including Go, npm, cargo, uv, pipx and the Python user base; the separate `$HOME/.agentainer/rustup` directory is outside that reset. See [customization](customization.md#project-dependencies-and-installed-tools).

The optional integration check runs from the repository root against an existing local image:

```sh
python3 tests/host/test-language-tooling.py --image localhost/agentainer:dev
```

It does the following:

- Installs the servers and a TypeScript 6 fallback project in a disposable persistent home.
- Checks LSP initialization and document symbols, and rejects a fake server.
- Recreates the container with networking disabled.
- Uses only `cx-*` names, runs one container at a time, and removes its containers and volume.

Use `--runtime docker` for Docker Engine. Installation needs network access to the Go module proxy, npm and the Rust distribution server. The check does not build an image, modify a personal home or make model requests.

The manual workflow [`.github/workflows/optional-tooling.yml`](../.github/workflows/optional-tooling.yml) (`workflow_dispatch`) builds the image and runs this check and the [Playwright check](browser-testing.md#verify-execution) with Docker on amd64 and arm64 runners. Not verified: the workflow has no runs yet (`gh run list --workflow optional-tooling.yml` returns none).
