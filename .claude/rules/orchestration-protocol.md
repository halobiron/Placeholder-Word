# Orchestration Protocol — BMAD Agent Hierarchy

## Role Hierarchy

AgentKit uses BMAD-inspired agent roles organized by responsibility:

| Role | Agent | Responsibility |
|------|-------|---------------|
| **Product Manager** | `pm-agent` | Defines WHAT — PRD, story creation, backlog grooming |
| **Architect** | `architect` | Defines HOW — architecture, ADRs, tech decisions |
| **Scrum Master** | `scrum-master` | Manages WHEN — sprints, prioritization, ceremonies |
| **Developer** | `planner` + devs | Builds IT — plans phases, implements within story scope |
| **QA Engineer** | `qa-engineer` | Validates BEFORE — test plans, acceptance criteria |
| **Tester** | `tester` | Validates AFTER — runs tests, coverage analysis |
| **Reviewer** | `code-reviewer` | Guards QUALITY — code review, architecture conformance |

---

## Context Chain Enforcement (MANDATORY)

When spawning subagents via Task tool, **ALWAYS** inject relevant artifacts from previous phases:

| Subagent | Must Receive |
|----------|-------------|
| `pm-agent` | `plans/artifacts/product-brief.md` (if exists) |
| `architect` | `plans/artifacts/PRD.md` (MANDATORY) |
| Story creation | `plans/artifacts/PRD.md` + `plans/artifacts/architecture.md` |
| `qa-engineer` | Story file + `plans/artifacts/PRD.md` (acceptance criteria) |
| Dev agents | Story file + `plans/artifacts/architecture.md` + `plans/artifacts/project-context.md` |
| `code-reviewer` | `plans/artifacts/architecture.md` (conformance check) |
| `tester` | Story file + test plan (if exists) |

**Rule:** If a mandatory artifact is missing, STOP and notify user. Do not proceed with assumptions.

---

## Delegation Context (MANDATORY)

When spawning subagents, **ALWAYS** include in prompt:

1. **Work Context Path**: The git root of the PRIMARY files being worked on
2. **Artifacts Path**: `{work_context}/plans/artifacts/` for that project
3. **Stories Path**: `{work_context}/plans/stories/` for that project
4. **Sprint Path**: `{work_context}/plans/sprints/` for that project
5. **Reports Path**: `{work_context}/plans/reports/` for that project

**Example:**
```
Task prompt: "Create architecture for authentication system.
Work context: /path/to/project
Artifacts: /path/to/project/plans/artifacts/
Read PRD: /path/to/project/plans/artifacts/PRD.md
Stories: /path/to/project/plans/stories/
Reports: /path/to/project/plans/reports/"
```

**Rule:** If CWD differs from work context, use the **work context paths**, not CWD paths.

---

## Orchestration Patterns

### Sequential Chaining (Phase-by-Phase)
Chain subagents for the BMAD lifecycle phases:
- **Phase 1 → 2 → 3 → 4**: Analysis → Planning → Solutioning → Implementation
- Each phase completes and produces artifacts before the next begins
- Context and artifacts are passed forward through the chain
- **Planning → Dev → Test → Review**: Within Phase 4 story cycle

### Parallel Execution (Within Phases)
Spawn multiple subagents simultaneously for independent tasks:
- **Multiple Researchers**: Different agents researching different topics in Phase 1
- **Parallel Story Dev**: Different developers working on independent stories in Phase 4
- **Code + Tests + Docs**: When implementing separate, non-conflicting components
- **Careful Coordination**: Ensure no file conflicts or shared resource contention
- When using mcp_agent_mail, file reservations prevent conflicts automatically

---

## Quick Flow Exception

For tasks matching ALL criteria:
- Single story, < 3 files, < 200 LOC
- No architectural change
- Clear scope without ambiguity
- User explicitly uses `/cook`, `/fix`, or tags as "quick"

→ Skip Phases 1-3, go directly to Phase 4 implementation cycle.
→ TDD rules still apply (write tests first).

---

## Agent Teams (Optional)

For multi-session parallel collaboration, activate the `/team` skill.
When using Agent Teams with mcp_agent_mail:
- Each agent gets a memorable identity (e.g., `dev-fast-rover`)
- Thread ID = story ID for all communications
- File reservations required before editing in team sessions
- See `.claude/rules/team-coordination-rules.md` for full protocol

Not part of the default orchestration workflow. See `.claude/skills/team/SKILL.md` for templates, decision criteria, and spawn instructions.
