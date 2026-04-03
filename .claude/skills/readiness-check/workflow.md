# Implementation Readiness Check Workflow

**Goal:** Validate cohesion across all planning artifacts before starting implementation.

**Your Role:** You are an Architect validating that all pieces fit together.

## Context Loading (ALL REQUIRED)
- `plans/artifacts/PRD.md`
- `plans/artifacts/architecture.md`
- `plans/epics/epic-*.md`
- `plans/stories/story-*.md`

## Validation Checks

### 1. Requirements Coverage
- [ ] Every functional requirement in PRD has at least one story
- [ ] Non-functional requirements are addressed in architecture
- [ ] No orphaned stories (stories without PRD requirement reference)

### 2. Architecture Completeness
- [ ] All components referenced in stories exist in architecture
- [ ] Data model covers all entities mentioned in stories
- [ ] API contracts defined for all story integration points
- [ ] Security requirements from PRD addressed in architecture

### 3. Story Quality
- [ ] Every story has acceptance criteria
- [ ] Every story has technical notes referencing architecture
- [ ] Story estimates are reasonable (no > 8h stories — should be split)
- [ ] Dependencies between stories are documented

### 4. Artifact Consistency
- [ ] PRD version matches architecture references
- [ ] Technology choices in architecture match project-context.md
- [ ] No contradictions between PRD and architecture constraints

## Output

Display results as checklist with pass/fail per item.
If all pass: "✅ Ready for implementation! Run `/sprint plan` to start."
If any fail: "⚠️ Issues found. Address before starting implementation." + list of issues.
