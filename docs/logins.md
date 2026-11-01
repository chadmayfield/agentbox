# Signing in

Put API keys and tokens in the env file (`~/.config/agentainer/env`, mode 600; see [env.example](../env.example)). Subscription logins happen inside the container and are stored in the home volume, so they survive a new container.

## Contents

- [Logins per agent](#logins-per-agent)
- [Which Claude login wins](#which-claude-login-wins)
- [GitHub and git](#github-and-git)
- [Credential exposure](#credential-exposure)

## Logins per agent

| Agent | Subscription login without a local browser | API key | Stored in |
|---|---|---|---|
| Claude Code | Run `claude setup-token` on a machine with a browser and set `CLAUDE_CODE_OAUTH_TOKEN`. Or run `/login` in the container and paste the code. | `ANTHROPIC_API_KEY` | `~/.claude/.credentials.json` |
| Codex | `codex login --device-auth`. Turn on device code login in your ChatGPT security settings first. | `printenv OPENAI_API_KEY \| codex login --with-api-key` | `~/.codex/auth.json` |
| Antigravity | Run `agy` and sign in (see the note below) | `GEMINI_API_KEY` plus `"modelProvider": "gemini"` in `~/.gemini/antigravity-cli/settings.json` | Not verified (see the note below) |
| OpenCode | `opencode auth login` | Provider variables such as `OPENROUTER_API_KEY` | `~/.local/share/opencode/opencode.db` |
| GitHub | n/a | `GH_TOKEN` (a fine-grained token) | Not in the home volume. `gh` reads `GH_TOKEN` from the environment, and `gh auth setup-git` writes only the credential helper to `~/.gitconfig`. `~/.config/gh/` comes into use only if you run `gh auth login`. |

Antigravity notes:

- Over SSH, `agy` prints a sign-in URL and asks you to paste back the code it shows. Not verified: whether it offers that flow in a container you reach without SSH.
- The install page names the operating system keyring as the login store. Not verified: where `agy` keeps the login in the container.

Sources: [Claude authentication](https://code.claude.com/docs/en/authentication), [Codex auth](https://learn.chatgpt.com/docs/auth), [Antigravity install](https://antigravity.google/docs/install.md), [OpenCode v2 providers](https://opencode.ai/v2/docs/cli/providers), [gh environment](https://cli.github.com/manual/gh_help_environment), [gh auth setup-git](https://cli.github.com/manual/gh_auth_setup-git), [gh auth login](https://cli.github.com/manual/gh_auth_login).

The env file uses the engine's `NAME=value` format, not shell syntax. Do not quote values, use `export`, put spaces around `=`, or append comments to a value. A bare name imports that variable from the launching host environment ([Podman env files](https://docs.podman.io/en/latest/markdown/podman-run.1.html), [Docker env files](https://docs.docker.com/reference/cli/docker/container/run/#env)).

## Which Claude login wins

When several credentials are present, Claude Code uses the first one in this order ([authentication precedence](https://code.claude.com/docs/en/authentication#authentication-precedence)):

1. Cloud provider credentials, when `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX` or `CLAUDE_CODE_USE_FOUNDRY` is set
2. `ANTHROPIC_AUTH_TOKEN`
3. `ANTHROPIC_API_KEY`
4. The output of an `apiKeyHelper` script
5. `CLAUDE_CODE_OAUTH_TOKEN`
6. Anthropic profile and federation credentials. A profile written by `ant auth login` ranks here only when `ANTHROPIC_PROFILE` names it, and below `/login` otherwise.
7. A `/login` session

A signed-in Claude apps gateway session outranks the whole list. An `ANTHROPIC_API_KEY` in the env file therefore bills the API even if you signed in with a subscription. Claude asks once in interactive mode before it uses that key.

## GitHub and git

When `GH_TOKEN` or `GITHUB_TOKEN` is set, the entrypoint runs `gh auth setup-git`, so `git push` over HTTPS uses the token. It skips the step when this container's `gh` is already the credential helper, so containers sharing a home volume do not rewrite `~/.gitconfig` on every start.

`GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` set your git identity when `~/.gitconfig` has none. If they later differ from the configured identity, git uses them as the author and the configured identity as the committer, and the entrypoint prints a warning.

## Credential exposure

Every process in the container can read every variable in the env file. See [what the container isolates](security.md#credentials-and-runtime-settings).
