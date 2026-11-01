# Agentainer environment

You are running inside an Agentainer container.

- Your project usually lives in `/workspace`. Only the paths mounted by the launcher or deployment are shared with the host or stored on volumes.
- Your home is `/home/agent`. Its contents survive container recreation when it is mounted from a persistent volume or host directory.
- `sudo` is usually disabled. If it works, packages installed with `apt` are lost when the container is recreated (for example on an image upgrade).
- Install extra tools in user space: `uv tool install`, `pipx install`, `npm install -g`, `cargo install` or `go install`. They go to `/var/lib/agentainer/active`. Whether they survive the container being recreated depends on `AGENTAINER_TOOLS` (`ephemeral` or `persist`).
- Python refuses `pip install --user` here (PEP 668). Use `uv`, `pipx` or a virtual environment.
- Credentials may come from environment variables or from agent login files in your home. Never print them, copy them into other files, or commit them.
- Follow the repository's commit, push and approval rules. Do not treat these environment instructions as permission to commit or push.

Edit this file to add your own instructions. It is `~/.agentainer/AGENTS.md`. Agentainer links each agent to it when that agent's own user instruction file is missing. If that file already exists, Agentainer leaves it as is, and the agent reads this file only if yours imports or links it.

## Working rules

- Read the repository's instructions and inspect the relevant code before changing files. Follow its conventions and approval requirements.
- Never assume. Never guess. Always verify. Check commands, flags, paths and tool capabilities using installed help, official documentation or commands you run. State what you could not verify.
- If instructions are complicated or ambiguous and the intended outcome is unclear, ask the user what they want before proceeding with the affected work.
- Keep changes focused on the requested task. Preserve unrelated work and user-owned files.
- Run the checks relevant to the change. Report their actual results, including failures and checks you could not run. Do not claim a check passed unless you ran it or inspected its result.
- Never expose credentials or personal information in source code, logs, examples, commits or pull requests. Use generic placeholders in material intended for sharing.
- Describe what changed, why it changed and how you verified it. Identify any remaining limitations.

## Writing outside chat

For text covered below, read `/usr/local/share/agentainer/skills/unslop/SKILL.md` and apply its editing rules within this scope:

- Apply the full rules to docs, READMEs, plans, commit messages, PR and issue text, UI and marketing copy, user-facing errors, code comments and docstrings, and reports or other files written for the user. Short comment fragments and `TODO:` or `NOTE:` labels are allowed.
- Apply the full rules to instruction files, skills and memory notes, except the bold-formatting rule. Preserve required structures, including frontmatter and memory fields.
- For logs and internal errors, remove only obvious AI tells such as filler, fancy vocabulary, em dashes, emojis and chatbot phrases. Short, clipped wording is allowed.
- Exempt chat replies, including Insight blocks, machine-generated output such as lockfiles, generated code and build output, config keys and values, test fixture data, quotations and code identifiers.
- Apply the rules only to text you write or change. Do not reword untouched lines. Files written for the user remain covered even when created during a chat.

The skill comes from Cursor's pstack project. Its upstream attribution and MIT license are in `/usr/local/share/agentainer/skills/unslop/LICENSE`. Edit this section to customize its scope.
