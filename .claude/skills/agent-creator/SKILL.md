---
name: ak:agent-creator
description: Automatically create configuration files (.md) for new coding agents, ensuring compliance with the BMAD agile lifecycle hierarchy.
version: 1.0.0
argument-hint: "[agent-name]"
---

# Agent Creator

Generate new `.claude/agents/<agent-name>.md` files based on user requirements to quickly onboard new specialized coding agents into the BMAD lifecycle.

## Workflow

When asked to create a new agent:

1. **Information Gathering**:
   - Ask the user (if not already provided in the prompt) for the specific role or purpose of the agent.
   - Ask which tools the agent needs (e.g., Glob, Grep, Read, Edit, Bash).
   - Determine whether the agent operates in Phase 2/3 (planning) or Phase 4 (execution).

2. **Template Expansion**:
   - Use `references/agent-template.md` as the exact boilerplate.
   - Fill in the required brackets `[agent-name]`, `[description]`, `[model]`, `[tools]`, and `[role description]`.
   - Customize the instructions depending on the specific tasks requested.

3. **File Creation**:
   - Use the `Write` or `write_to_file` tool to save the filled template to `.claude/agents/<agent-name>.md`.
   - The filename must be kebab-case.

4. **Validation**:
   - Confirm to the user that the file was created.
   - Remind the user to run `python3 .claude/scripts/generate_catalogs.py --commands` or `--skills` if they want to update system logs manually.

## Core Directives

- **DO NOT** create config variables outside the `.md` file unless the user explicitly asks for `.claude/teams/<agent-name>/config.json`.
- Treat the `.md` file as the absolute config for a coding agent.
- Ensure the agent is strictly tied to token optimization guidelines.
