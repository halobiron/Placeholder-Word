# Primary Workflow — BMAD Agile Lifecycle

**IMPORTANT:** Analyze the skills catalog and activate the skills that are needed for the task during the process.
**IMPORTANT**: Ensure token efficiency while maintaining high quality.

---

## Quick Flow (Small, Well-Understood Tasks)

For tasks that match ALL of the following, skip to **Phase 4 directly**:
- Explicitly tagged as "quick" by user, OR uses `/cook` or `/fix`
- Single story scope (< 3 files, < 200 LOC changes)
- No new architecture decisions needed
- Clear scope without ambiguity

When using Quick Flow:
1. Dev writes tests first (TDD still applies)
2. Implement, test, review — standard dev cycle
3. Skip phases 1-3 entirely

---

## Full Flow — BMAD 4-Phase Lifecycle

### Phase 1: Analysis (Optional)

Explore the problem space before committing to planning.

- `/brainstorm` → brainstorming report in `plans/reports/`
- Delegate multiple `researcher` agents in parallel for domain/market/technical research
- `/research` → research reports in `plans/reports/`
- Output: `plans/artifacts/product-brief.md` (optional but recommended)

**Gate:** No gate — analysis is optional. Proceed to Phase 2 when ready.

---

### Phase 2: Planning (Required)

Define WHAT to build and for whom.

1. Delegate to `pm-agent` → run `/prd` workflow
   - Input: user requirements, product-brief.md (if exists)
   - Output: `plans/artifacts/PRD.md`
2. Optional: `/ux-design` → `plans/artifacts/ux-spec.md`

**Gate:** PRD must be created and approved by user before proceeding to Phase 3.

---

### Phase 3: Solutioning (Required)

Decide HOW to build it. Break work into implementable stories.

1. Delegate to `architect` → run `/architecture` workflow
   - Input: `plans/artifacts/PRD.md` (MANDATORY context)
   - Output: `plans/artifacts/architecture.md`

2. Delegate to `pm-agent` → run `/story create` workflow
   - Input: `plans/artifacts/PRD.md` + `plans/artifacts/architecture.md` (MANDATORY)
   - Output: `plans/epics/epic-{slug}.md` + `plans/stories/story-{slug}.md`

3. Run `/readiness-check` → validate cohesion across PRD ↔ architecture ↔ stories

**Gate:** Architecture + at least 1 story must exist and be approved before Phase 4.

---

### Phase 4: Implementation (Sprint Cycle)

Build it, one story at a time. Sprint duration: **1 week**.

#### Sprint Planning
- Delegate to `scrum-master` → run `/sprint plan`
- Output: `plans/sprints/sprint-status.yaml`

#### Story Build Cycle (repeat per story)

```
1. QA Engineer → write test plan (tests/plans/story-{slug}-test-plan.md)
2. Dev Agent  → write FAILING tests first (TDD)
3. Dev Agent  → implement until tests pass
4. Dev Agent  → delegate to `code-reviewer` (check architecture conformance)
5. QA Agent   → run acceptance tests against story criteria
6. Story      → marked done in sprint-status.yaml
```

**Gate per story:**
- Test plan must exist BEFORE dev starts (TDD rule)
- Code review must pass
- Acceptance criteria from story file must be verified

#### Sprint Close
- After all sprint stories complete: delegate to `scrum-master` → `/retro`
- Output: `plans/sprints/sprint-{n}-retro.md`
- `docs-manager` updates `docs/` if needed

---

## Phase Navigation: `/agile-help`

Not sure which phase you're in? Run `/agile-help` — it scans `plans/artifacts/`, `plans/stories/`, and `plans/sprints/` to detect current state and recommend next action.

---

## Context Chain (Critical)

Each phase produces artifacts that are **mandatory context** for the next:

```
product-brief.md → PRD.md → architecture.md → story-{slug}.md → sprint-status.yaml
     ↓                ↓            ↓               ↓                  ↓
  (Feeds PM)    (Feeds Arch)  (Feeds PM+SM)   (Feeds Dev+QA)     (Feeds SM)
```

**Rule:** When spawning subagents, ALWAYS inject the relevant artifacts as context. See `orchestration-protocol.md` for details.

---

## Debugging & Bug Fixes

When a user reports bugs or issues:
1. Delegate to `debugger` agent → analyze logs and reports
2. Read summary → implement fix
3. Delegate to `tester` agent → run tests
4. If tests fail, fix and repeat from step 3

---

## Visual Explanations

When explaining complex code, protocols, or architecture:
- Use `/preview --explain <topic>` for visual explanation with ASCII + Mermaid
- Use `/preview --diagram <topic>` for architecture and data flow diagrams
- Use `/preview --slides <topic>` for step-by-step walkthroughs
- Plan context: visuals save to plan folder from `## Plan Context` hook injection
