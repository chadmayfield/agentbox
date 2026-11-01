# Setting up the agents

This page shows where each agent keeps its settings, instructions and skills inside the container, and how to set up status lines, plugins and MCP logins. Your settings, instructions and skills live under `/home/agent`, the persistent home, so they survive a new container. Run the commands inside the container (`bin/agentainer shell` or a tmux window).

The pinned versions are in [`versions.env`](../versions.env): Claude Code 2.1.309, Codex 0.166.0, Antigravity CLI 1.4.12 and OpenCode 2.2.5. The commands below exist in those versions (`--help` in the image). [Signing in](logins.md) covers logins.

## Contents

- [Where each agent keeps things](#where-each-agent-keeps-things)
- [Skills](#skills)
- [Status lines](#status-lines)
- [Plugins](#plugins)
- [MCP servers and authentication](#mcp-servers-and-authentication)
- [Keeping settings across upgrades](#keeping-settings-across-upgrades)
- [Check the setup](#check-the-setup)

## Where each agent keeps things

| Agent | Settings | Global instructions | Personal skills |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json`; `CLAUDE_CONFIG_DIR` moves it ([settings](https://code.claude.com/docs/en/settings)) | `~/.claude/CLAUDE.md`, which imports the shared file | `~/.claude/skills/<name>/SKILL.md` |
| Codex | `~/.codex/config.toml`; `CODEX_HOME` moves it ([config reference](https://learn.chatgpt.com/docs/config-file/config-reference)) | `~/.codex/AGENTS.md`, a symlink to the shared file | `~/.agents/skills/` |
| Antigravity CLI | `~/.gemini/antigravity-cli/settings.json` ([CLI reference](https://antigravity.google/docs/cli/reference#configuration-keys-settingsjson)) | `~/.gemini/AGENTS.md`, a symlink to the shared file | `~/.gemini/config/skills/` |
| OpenCode | `~/.config/opencode/opencode.json` and `cli.json`; `XDG_CONFIG_HOME` moves them ([config](https://opencode.ai/v2/docs/config), [CLI settings](https://opencode.ai/v2/docs/cli/config)) | `~/.config/opencode/AGENTS.md`, a symlink to the shared file | `~/.config/opencode/skills/` |

- The shared instruction file is `~/.agentainer/AGENTS.md`. [AGENTS.md](configuration.md#agentsmd) explains the links, when the image updates the file, and what happens when one of these paths already holds your own file.
- [Default configuration](defaults.md#agent-configurations) lists what the image seeds in each settings file.
- `opencode debug paths` prints OpenCode's resolved config, data and cache directories.
- Agentainer's instruction links use the fixed instruction paths in this table and do not follow these variables.
- The MCP sync writes other files, such as `~/.claude.json` and `~/.gemini/config/mcp_config.json`. [MCP servers](configuration.md#mcp-servers) lists them; `CLAUDE_CONFIG_DIR` is the only override the sync follows.

## Skills

A skill is a directory with a `SKILL.md` file. Each agent reads personal skills from its own directories, and project skills from directories in the repository:

| Agent | Personal | Project | Source |
|---|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` | [Claude skills](https://code.claude.com/docs/en/skills) |
| Codex | `~/.agents/skills/`; `/etc/codex/skills/` for admin skills | `.agents/skills/` from the working directory up to the repository root | [Codex skills](https://developers.openai.com/codex/skills) |
| Antigravity CLI | `~/.gemini/config/skills/`; the CLI also reads `~/.gemini/antigravity-cli/skills/` and `~/.gemini/skills/` | `.agents/skills/` up to the repository root | [Antigravity skills](https://antigravity.google/docs/skills#cli-skill-locations) |
| OpenCode | `~/.config/opencode/skills/`; also `~/.claude/skills/` and `~/.agents/skills/` | `.opencode/skills/`, `.claude/skills/` and `.agents/skills/` | [OpenCode skills](https://opencode.ai/v2/docs/skills#discovery) |

Not verified: discovery from these directories with the pinned CLIs. For OpenCode, an earlier check found that its skill API listed no copied skills ([plugins](plugins.md#opencode)).

Claude Code documents that a skill folder in its personal location can be a symlink to a directory elsewhere ([Claude skills](https://code.claude.com/docs/en/skills)). Whether the other agents follow symlinked skill directories is not verified.

The image's [unslop skill](configuration.md#writing-rules) is not registered as a native skill in any agent. The shared instructions tell agents to read it.

## Status lines

| Agent | What you can configure | Source |
|---|---|---|
| Claude Code | `statusLine` in `~/.claude/settings.json` runs a command. Claude passes session data as JSON on stdin and shows what the command prints. `/statusline` can write the script for you. | [Claude status line](https://code.claude.com/docs/en/statusline) |
| Codex | `tui.status_line` in `~/.codex/config.toml` is an ordered list of built-in footer items; `null` turns it off. `/statusline` opens a picker that writes the list. It does not run a custom command. | [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference), [slash commands](https://learn.chatgpt.com/docs/cli/slash-commands.md) |
| Antigravity CLI | `statusLine` in `~/.gemini/antigravity-cli/settings.json` runs a command with `sh -c`. The CLI passes session state as JSON on stdin and shows what the command prints. `stack_with_default` keeps the built-in line as well. | [Antigravity status line](https://antigravity.google/docs/cli/statusline) |
| OpenCode | `mini.footer` in `~/.config/opencode/cli.json` shows or hides the `opencode mini` footer (activity, model, usage and context). The image seeds `"footer": "show"`. `session.sidebar` is `auto` (show the sidebar when space permits) or `hide`. | [CLI settings](https://opencode.ai/v2/docs/cli/config#mini), [sessions](https://opencode.ai/v2/docs/cli/config#sessions) |

OpenCode's CLI settings page documents no custom status-line command; whether OpenCode 2.2.5 supports one is not verified.

For Claude Code and Antigravity, keep the script in the home volume so it survives a new container. For example, in `~/.claude/settings.json`:

```json
{
  "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}
}
```

Make the script executable with `chmod +x`. `jq` is in the image for reading the JSON input. No status line is seeded, and abtop does not install one ([monitoring](monitoring.md#model-calls-and-controls)). Not verified: custom status-line scripts with the pinned Claude Code and Antigravity versions.

## Plugins

[Optional plugins](plugins.md) has each agent's plugin commands and the checks to run after installing. Plugin settings and files under `/home/agent` survive a new container. Software a plugin needs outside the home must be installed again after the container is recreated.

## MCP servers and authentication

Define shared servers once in `~/.agentainer/mcp.json` and let `agentainer-mcp sync` write them into each agent ([MCP servers](configuration.md#mcp-servers)). Keep secrets in your env file and refer to them as `${NAME}`. How each agent receives a secret, and how it signs in to an OAuth server:

| Agent | `${NAME}` secrets from `mcp.json` | OAuth login for a remote server |
|---|---|---|
| Claude Code | Passed through | `claude mcp login <name>`; `--no-browser` prints the URL for a headless session ([Claude MCP](https://code.claude.com/docs/en/mcp)) |
| Codex | `Authorization: Bearer ${NAME}` becomes `bearer_token_env_var`; other headers must be `${NAME}` alone | `codex mcp login <name>`; `--no-browser` prints the URL ([Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)) |
| Antigravity CLI | Not written. The next sync rewrites a server it manages, so a header you add to it by hand does not survive. Add the server under a name that `mcp.json` does not use, with `agy mcp add --type http --header "Authorization: Bearer <token>" <name> <url>`. | Not verified. `agy mcp` has no login subcommand in 1.4.12 ([Antigravity MCP](https://antigravity.google/docs/mcp)). |
| OpenCode | Written as `{env:NAME}` | `opencode mcp auth [<name>]` ([OpenCode MCP](https://opencode.ai/v2/docs/mcp-servers#oauth)) |

The sync accepts only the keys listed in [MCP servers](configuration.md#mcp-servers) and leaves out others, such as OAuth client settings, with a warning. Configure those in the agent itself, under a server name that `mcp.json` does not use. Not verified: completing an OAuth login in the container with any agent.

## Keeping settings across upgrades

Your settings, skills, plugins and logins stay in the home volume when you update the image. Startup changes only a few files; [upgrading](running.md#upgrading) lists them. To compare your files with new image defaults, look in `/etc/agentainer/home/`. To try changes without touching your main home, use a [separate test home](customization.md#image-upgrades-and-separate-test-homes).

## Check the setup

| Command | What it checks |
|---|---|
| `agentainer-doctor` (or `bin/agentainer doctor` on the host) | Settings file syntax, MCP sync state, tools and home permissions ([offline diagnostics](troubleshooting.md#offline-diagnostics)) |
| `agentainer-mcp list` | The MCP servers the sync manages |
| `claude doctor` | Claude Code installation and settings |
| `claude mcp list`, `claude plugin list` | Claude's MCP servers and plugins |
| `codex doctor` | Codex installation, config, auth and runtime health |
| `codex mcp list`, `codex plugin list` | Codex's MCP servers and plugins |
| `/debug-config` in a Codex session | Codex config layers and their precedence ([slash commands](https://learn.chatgpt.com/docs/cli/slash-commands.md)) |
| `agy mcp list`, `agy plugin list` | Antigravity's MCP servers and plugins |
| `opencode debug config` | OpenCode's configuration sources |
| `opencode mcp list`, `opencode plugin list` | OpenCode's MCP servers and plugins. An earlier check found that these list nothing even for entries OpenCode wrote itself ([MCP servers](configuration.md#mcp-servers)). |
