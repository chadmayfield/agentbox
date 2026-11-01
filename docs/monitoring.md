# Agent session monitoring

The image includes [abtop](https://github.com/graykode/abtop), a terminal monitor you start by hand. It is pinned in [`versions.env`](../versions.env) ([versions](versions.md)).

## Contents

- [Running abtop](#running-abtop)
- [Model calls and controls](#model-calls-and-controls)
- [Verification](#verification)

## Running abtop

Run inside the container, in a separate terminal or tmux window:

```sh
abtop
```

Upstream documents session, token, process and port monitoring for Claude Code, Codex and OpenCode ([supported agents](https://github.com/graykode/abtop#supported-agents)). Antigravity is not listed. OpenCode monitoring needs `sqlite3`, which the image includes. Inside a container, abtop sees only that container's processes; it is not a host-wide dashboard.

The TUI can terminate processes. `x` targets the selected session, and `X` targets orphan ports. Press `q` to quit and `t` to cycle themes. The theme choice persists in `~/.config/abtop/config.toml` on the home volume. See [upstream key bindings](https://github.com/graykode/abtop#key-bindings) and [configuration](https://github.com/graykode/abtop#configuration).

## Model calls and controls

The source links below point at the pinned release, `v0.5.5`.

- The TUI and `abtop --once` generate session titles through `claude --print`, sending excerpts of the first prompt and response. These calls can use Claude quota ([summary implementation](https://github.com/graykode/abtop/blob/v0.5.5/src/app.rs#L462)). Not verified: a supported switch that turns this off in the TUI.
- `abtop --json` prints a one-shot snapshot without the summary calls ([CLI source](https://github.com/graykode/abtop/blob/v0.5.5/src/lib.rs#L138)). Its output can contain transcript text and project paths, so keep it out of public logs.
- Agentainer does not start abtop, run `abtop --setup`, install its rate-limit hook or replace an existing status line.

## Verification

Verified by the offline container test: the installed version, parsing of live and demo JSON snapshots, and that those runs create no Claude settings. Not verified: detection and token accuracy for the pinned agents, rate-limit collection, interactive controls and cross-agent discovery.
