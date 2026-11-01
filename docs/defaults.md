# Default configuration

Agentainer seeds these files into a new home and leaves existing files unchanged. They live in `rootfs/etc/agentainer/home/` in the repository and `/etc/agentainer/home/` in the image. The shared instructions come from `rootfs/etc/agentainer/AGENTS.md`. The startup step is [`20-seed.sh`](../rootfs/usr/local/lib/agentainer/entrypoint.d/20-seed.sh).

No default contains an account, token, private endpoint or signing key. The Git identity and signing examples are comments. Runtime environment variables can still supply Git identity and enable the GitHub credential helper ([logins](logins.md)).

## Contents

- [Agentainer colors](#agentainer-colors)
- [Shell and command-line tools](#shell-and-command-line-tools)
- [Tmux](#tmux)
- [Vim and EditorConfig](#vim-and-editorconfig)
- [Agent configurations](#agent-configurations)
- [Existing homes](#existing-homes)

## Agentainer colors

The Agentainer colorscheme is inspired by [Ayu Dark](https://github.com/ayu-theme/ayu-colors/blob/master/themes/dark.yaml). It uses a pure black background, a subtle charcoal tmux bar, and a slate-blue Vim status line. It is a local adaptation, not the upstream Ayu theme. OpenCode uses its own built-in Ayu theme.

| Role | Color |
|---|---|
| Background | `#000000` |
| Selection and tmux bar | `#202020` |
| Normal text | `#bfbdb6` |
| Directories | `#8fb573` |
| Sockets and sticky directories | `#95e6cb` |
| Secondary text | `#747474` |
| Amber accents and links | `#e6b450` |
| Additions and executables | `#aad94c` |
| Removals and errors | `#f07178` |
| Blue accents | `#59c2ff` |
| Vim status line | `#253340` |

The shell exports `LS_COLORS` from `~/.config/agentainer/shell-theme.bash`. It gives `ls` and eza muted green directories (`#8fb573`), amber symbolic links and green executables. Edit that file to customize the file colors. Agentainer does not change the host terminal's ANSI palette, which bat's `ansi` theme uses.

Sockets use teal. Setuid executables and world-writable directories without the sticky bit use red on a muted dark red background. Setgid executables use amber on dark amber. Sticky shared directories use muted green on dark green; other sticky directories use teal on dark teal. These explicit RGB colors do not depend on the terminal's ANSI palette. The special permission styles override ordinary directory and executable colors.

![GNU ls file types with the Agentainer palette](../artifacts/visual/screenshots/ls-colors.png)

The screenshot shows GNU `ls` output with the image's tools and these defaults. The last two rows show the missing-target and block-device styles. Ordinary source files and archives have no extension-specific colors.

Verified by [`tests/55-defaults.sh`](../tests/55-defaults.sh): RGB output from `ls`, eza and Git, eza's `LS_COLORS` override, uncolored redirected Git output, Vim and tmux settings, and that startup keeps edited color files. Not verified: how the colors look in your terminal. [Visual review](../tests/visual/README.md) generates an optional screenshot gallery.

## Shell and command-line tools

| File in home | Default |
|---|---|
| `.profile` | Ubuntu's login-shell profile, with `~/bin` and `~/.local/bin` added at the end of `PATH` so they never hide the image's tools |
| `.bashrc` | Ubuntu shell defaults, append-only history, Git and fzf completion, `EDITOR=vim`, `VISUAL=vim`, and a `less` pager |
| `.bash_logout` | Copied from Ubuntu's `/etc/skel` |
| `.config/agentainer/shell-theme.bash` | Black panes, amber username, blue hostname, gray path, and colored file listings |
| `.config/eza/theme.yml` | Ayu-inspired file types, permissions, sizes, owners, dates and Git indicators |
| `.config/fzf/config` | Black background with charcoal selection and Ayu accents |
| `.config/bat/config` | Built-in `ansi` theme, line numbers, changes and headers, automatic paging |
| `.gitconfig` | Vim editor, `main` initial branch, required identity, common aliases, Ayu diff/status/branch colors and `push.default=simple` |
| `.config/git/ignore` | OS metadata, Vim swap files and editor backups |

Shell behavior:

- Bash loads Ubuntu's `/etc/skel/.bashrc` first. It keeps Ubuntu's `ll`, `la` and `l` aliases and adds `..`, `...` and `v`.
- History ignores adjacent duplicates and commands that start with a space. Shells append history when they exit; running shells do not import each other's history.
- `EDITOR`, `VISUAL`, `PAGER`, `LESS` and `FZF_DEFAULT_OPTS_FILE` keep existing nonempty values.
- Git completion comes from `/usr/share/bash-completion/completions/git`. fzf integration uses its `--bash` option.
- `less` keeps color escapes with `LESS=FRX`. Git uses `less -FRSX`, which also truncates long lines.
- No shell alias bypasses agent approvals or runs a Git push or rebase.

Colors:

- The bat build does not include Ayu. Its `ansi` theme uses the terminal's ANSI palette instead of downloading a theme.
- fzf uses the explicit RGB palette in its options file.
- eza reads `~/.config/eza/theme.yml`. `LS_COLORS` and `EZA_COLORS` take precedence over file-name colors. The theme also colors metadata in long listings such as `eza --long --group --header`.
- Git uses amber headings, gray context, green additions and red removals for diffs, with matching status, branch and log colors. `color.ui=auto` keeps redirected output free of color escapes.

Sources: [Bash manual](https://www.gnu.org/software/bash/manual/), [Bash history](https://www.gnu.org/software/bash/manual/html_node/Bash-History-Facilities.html), [fzf shell integration](https://github.com/junegunn/fzf#setting-up-shell-integration), [bat configuration](https://github.com/sharkdp/bat#configuration-file), [eza themes and precedence](https://github.com/eza-community/eza-themes), [Git pager](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corepager), [Git color settings](https://git-scm.com/docs/git-config), [log color formatting](https://git-scm.com/docs/pretty-formats), [Ayu colors](https://github.com/ayu-theme/ayu-colors/blob/master/themes/dark.yaml).

## Tmux

`.tmux.conf` provides a charcoal bar with amber text. The image's `/etc/tmux.conf` supplies mouse support, truecolor and agent terminal settings. Windows and panes start at 1, and windows renumber when closed.

Press `Ctrl-b`, release it, then press the listed key:

| Key | Action |
|---|---|
| Pipe character, Shift-backslash on a US keyboard | Split left and right in the current directory |
| `-` | Split top and bottom in the current directory |
| `c` | Open a window in the current directory |
| `r` | Reload the personal tmux config |
| Uppercase `H`, `J`, `K`, `L` | Resize left, down, up or right; repeat within 750 ms |
| `[` | Enter copy mode; use `h/j/k/l`, `v` to select, `y` to copy, or `q` to leave |

Activity in other windows marks their status entries without an audible bell. Clipboard copying uses `set-clipboard=external` and OSC 52. The outside terminal must accept it; transfer to the host clipboard is not verified by the container tests ([tmux clipboard](https://github.com/tmux/tmux/wiki/Clipboard)). Commands and options follow the [tmux manual](https://github.com/tmux/tmux/blob/master/tmux.1).

## Vim and EditorConfig

`.vimrc` and `.vim/colors/agentainer.vim` provide black editing panes, Ayu-inspired syntax colors and a slate-blue status line distinct from tmux. Vim shows line numbers, the current line and trailing whitespace. Search is incremental and ignores case unless the pattern contains uppercase characters. Press Escape twice to clear search highlighting.

Indentation defaults to four spaces, with two for YAML, JSON, JavaScript, TypeScript, HTML and CSS. Vim's Makefile settings preserve tabs. Vim loads its bundled EditorConfig package so project rules take precedence. The settings follow the installed runtime's `:help options`, `:help last-position-jump`, `:help netrw-:Lexplore` and `:help editorconfig`.

Undo, swap and backup files live in private directories under `~/.vim/`. These files can retain earlier contents of credentials or other sensitive files after the original changes or disappears. Avoid editing secrets in this shared home, or use Vim settings that disable the recovery files you do not want. Vim returns to the last cursor position except for commit messages, rebase instructions and diff mode. Press backslash then `e` to toggle a full-height browser on the right, using 25% of the window width.

An EditorConfig file applies to files in its directory and descendants, not to unrelated directories. A home `.editorconfig` would not control `/workspace`. Copy the template `~/.config/agentainer/editorconfig` into a project's `.editorconfig` when the project has none. Agentainer never writes it into your workspace ([EditorConfig location and precedence](https://editorconfig.org/#file-location)).

## Agent configurations

| File in home | Default and source |
|---|---|
| `.claude/CLAUDE.md` | One line, `@~/.agentainer/AGENTS.md`, which imports the shared instructions ([AGENTS.md](configuration.md#agentsmd)) |
| `.claude/settings.json` | Shared `AGENTS.md` integration, stable updates, manual permissions, explanatory output, turn durations and terminal-bell notifications. Includes the published editor schema. [Settings and schema](https://code.claude.com/docs/en/settings), [output styles](https://code.claude.com/docs/en/output-styles), [duration setting](https://code.claude.com/docs/en/settings-reference#showturnduration), [notifications](https://code.claude.com/docs/en/terminal-config#get-a-terminal-bell-or-notification) |
| `.codex/config.toml` | File-backed login storage and explicit `approval_policy=on-request`. `sandbox_mode = "danger-full-access"`, because the file's comment records that Codex's bubblewrap sandbox cannot start in the container ([agent permissions](security.md#agent-permissions)). [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference) |
| `.gemini/antigravity-cli/settings.json` | Terminal colors, `toolPermission=request-review`, Vim as the external editor and completion notifications. [Antigravity settings](https://antigravity.google/docs/cli/reference#configuration-keys-settingsjson) |
| `.config/opencode/opencode.json` | Disabled updater and the published editor schema. [Config](https://opencode.ai/v2/docs/config) |
| `.config/opencode/cli.json` | Built-in `ayu` dark theme, notifications without sound, explicit prompting for permission requests, diff layout selected by available width, word wrapping and a diff file tree. The mini interface shows its status footer and turn summaries. Includes the published CLI schema. [CLI settings](https://opencode.ai/v2/docs/cli/config), [themes](https://opencode.ai/v2/docs/themes) |
| `.config/agentainer/editorconfig` | Project EditorConfig template ([Vim and EditorConfig](#vim-and-editorconfig)) |

Models, accounts and provider URLs are left for you to configure. Claude, Antigravity and OpenCode keep the approval settings listed above. Codex runs with `on-request` and `danger-full-access`; [agent permissions](security.md#agent-permissions) explains what that allows.

Verified by `tests/55-defaults.sh` on a fresh named home volume: the seeded files match the image defaults, `claude doctor` reports no invalid setting and reports a deliberately bad one, OpenCode applies the Ayu theme and falls back to its default theme when `cli.json` is invalid, and a second start keeps edits to all four agents' files. `claude doctor` exits 0 even when it reports invalid settings, so read its report instead of relying on the exit status. Not verified: model-driven approval behavior, account access, and notification delivery.

Notifications depend on the host terminal and tmux settings. Claude uses a terminal bell, so the container needs no desktop notification command. Antigravity's notification option includes a terminal chime. OpenCode's sound option is separate and off.

Customize models, providers, plugins and hooks in your own home files. Keep API keys in the runtime environment or the agent's login store. Claude and Antigravity use strict JSON, so keep notes outside the file. OpenCode supports JSONC, but Agentainer's MCP sync writes `opencode.json` and stops if `opencode.jsonc` exists. Codex's TOML supports comments. No status-line command or hook is seeded; [setting up the agents](agents.md#status-lines) covers each agent's status line.

## Existing homes

Image upgrades do not replace your `.bashrc`, `.gitconfig`, `.vimrc`, `.tmux.conf` or agent settings. Compare desired files with `/etc/agentainer/home/` and apply changes yourself. [Upgrading](running.md#upgrading) lists the few files that startup does change.

Changes to image seed files do not modify running containers.
