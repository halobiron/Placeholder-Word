# Agile Help — Phase Detection & Guidance

**Goal:** Detect current project phase and recommend the next action.

## Detection Logic

Scan the project state and determine which BMAD phase the user is in:

### Check Artifacts

```
plans/artifacts/product-brief.md  → exists? → Phase 1 done
plans/artifacts/PRD.md            → exists? → Phase 2 done
plans/artifacts/architecture.md   → exists? → Phase 3 started
plans/stories/story-*.md          → any exist? → Phase 3 done
plans/sprints/sprint-status.yaml  → exists? → Phase 4 started
```

### Decision Tree

| State | Phase | Recommendation |
|-------|-------|---------------|
| No artifacts at all | Pre-Phase 1 | "Start with `/brainstorm` or skip to `/prd` if you know what to build" |
| product-brief exists, no PRD | Phase 1 done | "Run `/prd` to create Product Requirements Document" |
| PRD exists, no architecture | Phase 2 done | "Run `/architecture` to create technical design" |
| Architecture exists, no stories | Phase 3 started | "Run `/story create` to break down into stories" |
| Stories exist, no sprint | Phase 3 done | "Run `/readiness-check` then `/sprint plan` to start building" |
| sprint-status exists | Phase 4 active | "Run `/sprint status` to see progress, or `/story dev {slug}` to implement next story" |
| All stories done | Sprint complete | "Run `/retro` for retrospective, then `/sprint plan` for next sprint" |

### Output Format

```
📍 Current Phase: Phase {N} — {Phase Name}
✅ Completed: {list of completed phases}
➡️ Next Step: {recommended action}

Available commands:
  /prd             — Create PRD (Phase 2)
  /architecture    — Create Architecture (Phase 3)
  /story create    — Create Stories (Phase 3)
  /readiness-check — Validate readiness (Phase 3→4)
  /sprint plan     — Plan sprint (Phase 4)
  /story dev {slug} — Implement story (Phase 4)
  /retro           — Sprint retrospective (Phase 4)
```
