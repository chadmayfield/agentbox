# Configuration

This page covers the shared `AGENTS.md`, MCP servers, tools that agents install, OpenRouter and startup messages. [Default configuration](defaults.md) covers the seeded shell, Git, tmux, Vim, EditorConfig and agent settings. Existing user files are preserved.

## Contents

- [AGENTS.md](#agentsmd)
  - [Writing rules](#writing-rules)
- [MCP servers](#mcp-servers)
- [Tools that agents install](#tools-that-agents-install)
- [OpenRouter](#openrouter)
- [Startup messages](#startup-messages)

## AGENTS.md

You keep one instruction file, `~/.agentainer/AGENTS.md`. Agentainer connects each agent to it:

| Agent | Reads | How |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Contains `@~/.agentainer/AGENTS.md` ([imports](https://code.claude.com/docs/en/memory)) |
| Codex | `~/.codex/AGENTS.md` | Symlink |
| Antigravity | `~/.gemini/AGENTS.md` | Symlink |
| OpenCode | `~/.config/opencode/AGENTS.md` | Symlink |

The entrypoint seeds `~/.claude/CLAUDE.md` and creates each symlink only when that path is missing. An existing `~/.claude/CLAUDE.md` is kept without a message. An existing regular file at one of the three symlink paths is kept with a warning. In both cases that agent reads the shared file only if your file imports or links it.

The seeded Claude settings set `instructionFiles` to `claude-md-and-agents-md`, so Claude Code loads both `CLAUDE.md` and `AGENTS.md` in a repo that has both ([instruction files setting](https://code.claude.com/docs/en/memory)). Each repo's own `AGENTS.md` still loads on top of yours.

The first start copies the image's default. A later image replaces your copy with its own default only when all of these hold:

- You never edited the file. It still matches a default this home has seen.
- The file is a regular file. A symlinked `~/.agentainer/AGENTS.md`, for example from a dotfiles repo, is never replaced.
- The image has a release version (`AGENTAINER_IMAGE_VERSION`), not a local build (`dev`).
- That version is newer than every recorded version that shipped your file's content. A prerelease can replace an older prerelease default, but never a default that a stable release shipped.

Release versions follow [SemVer](https://semver.org/), including dated development builds such as `0.1.0-dev.20261019.1`. A replacement keeps the file mode and prints one line. In every other case the file is not touched. If the image's default is one this home has not seen before, the entrypoint prints one notice; `agentainer-agents diff` shows the difference.

`~/.agentainer/agents-default.sha256` records every default the home has seen, one line per default and image version: `<sha256> <version>`. A line with only a hash comes from an image that did not record its version and counts as older than any release. So an older image never rolls the file back, and two images that share one home volume do not report each other's default more than once.

### Writing rules

The shared default tells agents to read `/usr/local/share/agentainer/skills/unslop/SKILL.md` before writing covered text. This is one image-owned copy of [Cursor's unslop skill](https://github.com/cursor/plugins/tree/main/pstack/skills/unslop), with the upstream [MIT license and attribution](https://github.com/cursor/plugins/blob/main/pstack/LICENSE). The build verifies both files against the commit and SHA-256 values in [`versions.env`](../versions.env). Upstream publishes no checksum files for these sources; the updater computes the recorded hashes from the same immutable commit.

The shared instructions set this scope:

| Content | Treatment |
|---|---|
| Docs, READMEs, plans, commits, PRs, issues, UI and marketing copy, user-facing errors, comments, docstrings and files written for the user | Full editing rules; short comment fragments and `TODO:` or `NOTE:` labels are allowed |
| Instruction files, skills and memory notes | Full rules except the bold-formatting rule; required structures stay intact |
| Logs and internal errors | Remove obvious AI tells; clipped wording is allowed |
| Chat replies and Insight blocks | Exempt |
| Generated output, lockfiles, generated code, config keys and values, test fixture data, quotations and code identifiers | Exempt |
| Untouched text | Leave unchanged |

Edit the writing section in `~/.agentainer/AGENTS.md` to customize or disable it. Homes with edited instructions or a local `dev` image keep their copy; compare the new section with `agentainer-agents diff` before adopting it.

Agentainer references the skill through the shared instructions. It does not register a native `/unslop` command or install the rest of pstack. Whether models follow the writing rules is not verified.

## MCP servers

Define servers once in `~/.agentainer/mcp.json`, in the `mcpServers` format most MCP server READMEs use:

```json
{"mcpServers": {
  "remote": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${EXAMPLE_TOKEN}"}},
  "everything": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything@2.0.0"]}
}}
```

The sample fixes the package version using [published npm metadata](https://registry.npmjs.org/@modelcontextprotocol/server-everything/2.0.0). Stdio MCP servers execute code with the filesystem access and environment their agent gives them. Review the server and its dependencies before adding it. Use explicit package versions or a locked local installation.

`agentainer-mcp sync` writes them into each agent's own configuration:

| Agent | Where |
|---|---|
| Claude Code | `mcpServers` in `~/.claude.json`, or `$CLAUDE_CONFIG_DIR/.claude.json` |
| Codex | `[mcp_servers.<name>]` tables in a marked block at the end of `~/.codex/config.toml` |
| Antigravity | `mcpServers` in `~/.gemini/config/mcp_config.json` |
| OpenCode | `mcp.servers` in `~/.config/opencode/opencode.json` |

The JSON paths and formats match output from `claude mcp add-json --scope user` and `agy mcp add`, checked in the image. Claude documents its [user scope](https://code.claude.com/docs/en/mcp).

When the sync runs:

- On container start, when `mcp.json` changed. Startup runs `agentainer-mcp sync --if-changed`.
- When you run `agentainer-mcp sync`, even if `mcp.json` did not change.
- A failed write leaves no success stamp, so the next start retries.

Ownership:

- `~/.agentainer/mcp-managed.json` records which servers the sync added, for all four agents. The sync adds, updates and removes only those servers and never touches servers you added yourself. `agentainer-mcp list` shows them.
- Deleting `mcp.json` removes the servers the sync added.
- Config files that are symlinks stay symlinks; the sync writes the file the link points to.
- Direct and startup syncs share one lock, so they run one at a time on a shared home volume. The lock does not coordinate with agents that write the same files, so stop those agents before you sync.
- A journal records config hashes and managed names before each write, so a restart can recover ownership after an interrupted sync. If the config changed during that interruption, the sync stops for inspection instead of claiming ownership.

Server names may use only letters, digits, `-` and `_`. Any other name stops the sync with an error such as `agentainer-mcp: server name 'my.server' may only use letters, digits, - and _; nothing changed`.

A server entry has these keys:

| Kind | Keys | `type` |
|---|---|---|
| Command | `command`, `args`, `env` | `stdio` (optional) |
| URL | `url`, `headers` | `http` (default) or `sse` |

Any other `type` stops the sync with an error and changes nothing. Other keys, such as `cwd`, `timeout` or `disabled`, are not passed on; the sync prints a warning naming them.

Keep secrets as `${NAME}` references to variables in your env file; no agent config receives the value. The sync writes literal values directly into agent config files and never passes server configuration to a child process. New config files have mode `0600`. Existing files keep their permissions unless a sync writes literal environment or header values; those writes remove group and other permissions.

Limits per agent:

| Agent | SSE servers | `${NAME}` references |
|---|---|---|
| Claude Code | Written as SSE | Passed through |
| Codex | Left out with a warning (streamable HTTP only) | `Authorization: Bearer ${NAME}` becomes `bearer_token_env_var`. Any other header must be `${NAME}` alone, with `Bearer <token>` stored in the variable. An `env` entry cannot rename a variable (`API_KEY=${OTHER}` is left out); give the variable the name the server expects. |
| Antigravity | Left out with a warning (`stdio` and `http` only) | Not supported. `env` entries that are `${NAME}` are left out, so the server inherits the container's environment. Headers that contain `${NAME}` are left out with a warning. The next sync rewrites a server it manages, so add an authenticated server by hand under a name that `mcp.json` does not use ([agents](agents.md#mcp-servers-and-authentication)). |
| OpenCode | Written as a remote server, with a warning that this is not verified | Written as `{env:NAME}` |

Codex rewrites `config.toml` itself. `codex plugin add` puts its tables between the marker comments, and `codex mcp add` can remove the first marker. The Codex sync handles this as follows:

- It finds its own servers by the names recorded in `~/.agentainer/mcp-managed.json`. Only when that file lists no Codex servers, as in a config from an older Agentainer, does it take the servers between intact markers that `mcp.json` still lists.
- It keeps every other table and every comment, and writes its servers as a new marked block at the end.
- On its servers it owns the keys it can write: `command`, `args`, `env`, `env_vars`, `url`, `bearer_token_env_var`, `http_headers` and `env_http_headers`. If `config.toml` sets one of these on its server but `mcp.json` does not, the sync removes it and prints a warning. Put the value in `mcp.json` to keep it.
- Other keys you set on one of its servers, such as `enabled`, `enabled_tools` or `tools.<tool>.approval_mode` ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)), stay with that server until you remove it from `mcp.json`.
- Before it writes, the sync parses the old and new file. If anything else would change, or `config.toml` is not valid TOML, it writes nothing, prints a warning and exits with status 1.

For Claude Code, Antigravity and OpenCode, a sync replaces the servers it manages, so settings you change inside one of those agents for such a server may not survive. If `~/.config/opencode/opencode.jsonc` exists, the OpenCode sync stops with an error, because it edits only `opencode.json`.

Verified by hand: Codex and Antigravity listed a synced server's tools, and `claude mcp list` reported it as connected. Not verified: OpenCode, whose `opencode mcp list` prints "No MCP servers configured" even for a server that `opencode mcp add` wrote itself.

[Setting up the agents](agents.md#mcp-servers-and-authentication) covers each agent's own MCP login commands.

## Tools that agents install

`AGENTAINER_TOOLS` decides where `npm -g`, `cargo install`, `go install`, `uv tool` and `pipx` put things:

| Value | Location | Survives a new container |
|---|---|---|
| `ephemeral` (default) | `/var/lib/agentainer/tools` | No |
| `persist` | `~/.agentainer/tools` | Yes |

- Set it in the runtime env file before you create the container. Changing it does not change an existing container's environment.
- Image tools come first on `PATH`, so an installed tool never hides an image tool.
- `persist` keeps the installation roots on the home volume. It does not record the install commands or reproduce the same versions in another home, so keep those in your own setup notes or a custom image.
- It covers these user package managers only, not OS packages installed with `sudo apt`.
- When the image changes and persisted tools exist, the entrypoint warns on each start. `agentainer-tools reset` moves all persisted roots (Go, npm, cargo, uv, pipx and the Python user base) to a dated backup. Resets share a lock and reserve unique backup paths across containers.
- `agentainer-tools status` shows the effective mode, the selected root and the entries in `bin`, `npm/bin` and `python/bin`. It does not list every package or cache.

Ubuntu's Python refuses `pip install` outside a virtual environment, `pip install --user` included (PEP 668), so use `uv`, `pipx` or a venv. `PYTHONUSERBASE` points into the same tools root, but plain `pip` never installs there.

The image has `ansible-core` (`ansible`, `ansible-playbook`, `ansible-galaxy` and the other commands) without the community collections. Install the ones you use with `ansible-galaxy collection install community.general`. They go to `~/.ansible/collections` on the home volume.

## OpenRouter

| Command | What it does |
|---|---|
| `openrouter-claude` | Runs `claude` against `https://openrouter.ai/api` with `OPENROUTER_API_KEY`, for that process only ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)). It also sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, which turns on the gateway model picker, unless you set it yourself. |
| `openrouter-codex` | Runs `codex` with an `openrouter` provider and the model `~openai/gpt-sol-latest`. `-m` picks another model ([OpenRouter guide](https://openrouter.ai/docs/cookbook/coding-agents/codex-cli)). |
| `opencode` | Built-in provider. Set `OPENROUTER_API_KEY` and use the full OpenRouter model ID after the `openrouter/` prefix, such as `openrouter/<vendor>/<model>` ([OpenCode providers](https://opencode.ai/v2/docs/providers)). |

The key reaches OpenRouter as a bearer token and appears in no argument list, log or file. Antigravity has no OpenRouter support.

Limits: Anthropic "doesn't support routing Claude Code to non-Claude models through any gateway" ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)). Codex accepts only `wire_api = "responses"`, so the endpoint must serve the OpenAI Responses API ([Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)).

## Startup messages

The entrypoint prints its messages on stderr, each starting with `agentainer:`. `AGENTAINER_QUIET=1` hides the line that lists which credential variables are set. Warnings and every other message still print.

If you do not set `AGENTAINER_QUIET`, the entrypoint sets it to `1` for a one-shot command, such as `podman run --rm IMAGE claude --version`, and to `0` for the default command, `sleep infinity`. Set `AGENTAINER_QUIET=0` to see the line for a one-shot command, or `AGENTAINER_QUIET=1` to hide it for a long-running container.
