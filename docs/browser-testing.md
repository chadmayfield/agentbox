# Optional browser testing

Install Playwright in the project that needs it. Agentainer supplies Node.js and npm; browsers and their OS libraries are optional. Playwright supports Ubuntu 26.04 on amd64 and arm64 ([system requirements](https://playwright.dev/docs/intro#system-requirements)). Follow an existing project's package-manager instructions and lockfile instead of creating a second setup.

## Contents

- [Allow OS dependency installation](#allow-os-dependency-installation)
- [Install the project dependency and browser](#install-the-project-dependency-and-browser)
- [Verify execution](#verify-execution)
- [Updates, recreation and cleanup](#updates-recreation-and-cleanup)
- [Verify the Agentainer instructions](#verify-the-agentainer-instructions)

## Allow OS dependency installation

An agent can run the project installation, browser download and smoke test below. Playwright's Linux libraries need root, and the launcher blocks sudo by default. Create a container with `--sudo` for that step, or use a custom image that already has the libraries. Downloading a browser does not supply its OS dependencies, and browser binaries must match the project's Playwright version ([Playwright browser requirements](https://playwright.dev/docs/browsers)).

Select an available image as described in [running Agentainer](running.md), then run this from the repository root for a separate browser-testing home:

```sh
AGENTAINER_HOME_VOLUME=agentainer-browser-home \
  bin/agentainer up --sudo --name agentainer-browser "$HOME/code"
bin/agentainer shell agentainer-browser
```

`$HOME/code` must exist on the host. The home volume persists browser downloads. OS libraries installed with sudo live in the container's writable layer. Repeat their installation when replacing the container, or include them in your [custom image](customization.md#customize-the-image-itself). The launcher preserves `--sudo` during updates ([launcher options](running.md#the-launcher)).

## Install the project dependency and browser

Inside the container, enter the project directory under `/workspace`. For a new, empty npm project:

```sh
npm init --yes
npm install --save-dev --save-exact @playwright/test
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
sudo ./node_modules/.bin/playwright install-deps chromium
./node_modules/.bin/playwright install --only-shell chromium
```

Keep `package.json` and `package-lock.json` in version control. For an existing locked npm project, use `npm ci` instead of the first two commands. Run the browser download as the normal `agent` user. See [Playwright installation](https://playwright.dev/docs/intro), [Linux dependencies](https://playwright.dev/docs/browsers#install-system-dependencies) and [npm dependency locking](project-tools.md#javascript-dependencies-and-package-manager-versions).

`--only-shell chromium` downloads Chromium's headless shell. It supports headless tests without a browser channel selection. Headed tests, code generation with a visible browser, or a configuration using `channel: 'chromium'` need the full browser instead: run `./node_modules/.bin/playwright install chromium`. Firefox and WebKit need their own downloads and OS dependencies ([browser installation choices](https://playwright.dev/docs/browsers#chromium-headless-shell)).

Use the same `PLAYWRIGHT_BROWSERS_PATH` when installing and running tests. Export it in each shell that runs Playwright, or add the export to your own container `~/.bashrc`. This path is on the home volume in either tools mode; `AGENTAINER_TOOLS=persist` is not required. It stores executables, not browser login sessions ([browser storage](https://playwright.dev/docs/browsers#managing-browser-binaries)).

## Verify execution

Create `browser-smoke.spec.cjs` in the project:

```js
const { test, expect } = require('@playwright/test');

test('Chromium renders, handles input and captures a screenshot', async ({ page }, testInfo) => {
  await page.route('**/*', route => route.abort());
  await page.setContent('<h1>Browser ready</h1><button onclick="this.textContent=\'Clicked\'">Try it</button>');
  await expect(page.getByRole('heading')).toHaveText('Browser ready');
  await page.getByRole('button', { name: 'Try it' }).click();
  await expect(page.getByRole('button')).toHaveText('Clicked');
  await page.screenshot({ path: testInfo.outputPath('browser-smoke.png') });
});
```

Run it with the project-local command:

```sh
./node_modules/.bin/playwright test browser-smoke.spec.cjs --workers=1 --reporter=line
```

The test renders a page, clicks a button, checks its new text and writes `browser-smoke.png` under `test-results/`. It aborts page network requests and needs no external website. A browser launch failure or failed assertion returns a nonzero exit code. See [test assertions](https://playwright.dev/docs/test-assertions), [request interception](https://playwright.dev/docs/network#handle-requests) and [screenshots](https://playwright.dev/docs/screenshots).

For an existing project, follow its Playwright configuration and test command. A development server inside the container can listen on `0.0.0.0`; use the launcher's [port publishing](running.md#development-server-ports) to open it in a host browser.

## Updates, recreation and cleanup

After updating the project's Playwright version, repeat `install-deps chromium` and the browser install command. Playwright versions select matching browser revisions. After replacing the container, restore the project's dependencies with `npm ci` if needed, export the same browser path and reinstall the OS libraries. Browser files remain on the persistent home. Reinstall browser files and project dependencies when changing architecture. See [Playwright browser versions](https://playwright.dev/docs/browsers) and [project environment portability](customization.md#project-dependencies-and-installed-tools).

Playwright removes unused browser revisions as clients are updated. `./node_modules/.bin/playwright install --list` shows installed browsers; `./node_modules/.bin/playwright uninstall` removes browsers for that Playwright installation. Avoid `uninstall --all` when other projects share the browser directory ([browser management](https://playwright.dev/docs/browsers#stale-browser-removal)).

Keep `node_modules/`, `test-results/` and any generated `playwright-report/` out of the project's Git history. Browser authentication state, traces and screenshots can contain application data; store and publish only the outputs you intend to share ([authentication state](https://playwright.dev/docs/auth)).

## Verify the Agentainer instructions

From this repository root, run the optional networked setup check against an existing local image:

```sh
python3 tests/host/test-playwright-setup.py --image localhost/agentainer:dev
```

Use `--runtime docker` for Docker Engine. The check does the following:

- Installs the Playwright version locked for [visual tests](../tests/visual/package.json), then Chromium's libraries and headless shell.
- Runs the smoke test, and checks that a deliberately wrong assertion fails.
- Recreates the container with the same home and workspace volumes, checks the browser file hashes, reinstalls the OS libraries and runs the test again.
- Creates one container at a time, uses only `cx-*` names and removes its containers and volumes. It does not build an image or mount a personal home.

Setup needs network access to npm, Ubuntu and Playwright downloads. The smoke test itself blocks page network requests.

The manual workflow [`.github/workflows/optional-tooling.yml`](../.github/workflows/optional-tooling.yml) (`workflow_dispatch`) builds the image and runs this check and the [language tooling check](language-tooling.md#updates-and-verification) with Docker on amd64 and arm64 runners. Not verified: the workflow has no runs yet (`gh run list --workflow optional-tooling.yml` returns none). See [CONTRIBUTING.md](../CONTRIBUTING.md#ci).
