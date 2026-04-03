# Agile Gate Enforcement

Gates are checkpoints between BMAD phases. They prevent skipping required steps.

## Phase Gates (Full Flow)

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | Analysis → Planning | No gate (analysis is optional) |
| G2 | Planning → Solutioning | `plans/artifacts/PRD.md` must exist and be approved |
| G3 | Solutioning → Implementation | `plans/artifacts/architecture.md` + at least 1 story must exist |
| G4 | Story → Dev | Test plan at `tests/plans/story-{slug}-test-plan.md` must exist |
| G5 | Dev → Done | Code review passed + QA acceptance confirmed |

## Quick Flow Bypass

Tasks may skip phases 1-3 (go directly to Phase 4) if ALL criteria are met:
- Explicitly tagged as "quick" by user, OR uses `/cook`, `/fix`
- Single story scope: < 3 files, < 200 LOC changes
- No new architecture decisions needed
- Clear scope without ambiguity

**Even in Quick Flow, TDD rules still apply (Gate G4).**

## Gate Enforcement Behavior

When a gate condition is not met:
1. **STOP** — do not proceed to the next phase
2. **INFORM** — tell the user which gate failed and why
3. **SUGGEST** — recommend the action to satisfy the gate
4. **WAIT** — wait for user acknowledgment before proceeding

Example:
```
⛔ Gate G2 failed: PRD not found.
Required: plans/artifacts/PRD.md
Action: Run `/prd` to create the PRD first.
```

## Gate Override

User can explicitly override any gate by saying:
- "skip gate" / "override" / "bypass"
- This should be logged in the plan notes as a risk

**Note:** Overriding gates is a conscious decision. The system should make it easy to follow the process, not force it.
