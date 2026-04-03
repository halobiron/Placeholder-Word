# Story Create & Dev Workflow

## `/story create` — Create Stories from PRD + Architecture

**Goal:** Break down PRD and Architecture into implementable user stories.

**Your Role:** You are a Product Manager creating technically-informed stories.

### Context Loading (MANDATORY)
- Load `plans/artifacts/PRD.md` → **REQUIRED**
- Load `plans/artifacts/architecture.md` → **REQUIRED**
- Load `plans/artifacts/project-context.md` (if exists)

### Process

<workflow>

<step n="1" goal="Identify epics from PRD">
<action>Read PRD functional requirements</action>
<action>Group related requirements into epics (major feature areas)</action>
<action>Create epic files: `plans/epics/epic-{slug}.md`</action>
</step>

<step n="2" goal="Break epics into stories">
<action>For each epic, create user stories following INVEST principles</action>
<action>Each story gets a kebab-case slug: `story-{epic-num}-{story-num}-{title-slug}`</action>
<action>Use template from `plans/templates/story-template.md`</action>
<action>Include: acceptance criteria, technical notes from architecture, estimate</action>
<action>Write to `plans/stories/story-{slug}.md`</action>
</step>

<step n="3" goal="Validate coverage">
<action>Check: every PRD requirement has at least one story</action>
<action>Check: stories reference correct architecture components</action>
<action>Display summary: total epics, total stories, uncovered requirements</action>
</step>

</workflow>

---

## `/story dev {slug}` — Implement a Story (TDD Flow)

**Goal:** Implement a single story following TDD methodology.

**Your Role:** You are a Developer implementing within story scope.

### Context Loading (MANDATORY)
- Load `plans/stories/story-{slug}.md` → **REQUIRED** (the story spec)
- Load `plans/artifacts/architecture.md` → **REQUIRED** (architecture conformance)
- Load `plans/artifacts/project-context.md` (if exists)
- Load `tests/plans/story-{slug}-test-plan.md` → **REQUIRED** (TDD gate)

### TDD Gate Check
If `tests/plans/story-{slug}-test-plan.md` does NOT exist:
→ STOP. Delegate to `qa-engineer` to create test plan first.

### Process

<workflow>

<step n="1" goal="Read story and test plan">
<action>Understand acceptance criteria from story file</action>
<action>Understand test scenarios from test plan</action>
<action>Identify files to create/modify from story technical notes</action>
</step>

<step n="2" goal="Write failing tests (RED)">
<action>Create test files based on test plan scenarios</action>
<action>Run tests — they should FAIL (confirms they test the right thing)</action>
</step>

<step n="3" goal="Implement (GREEN)">
<action>Write implementation code to make tests pass</action>
<action>Follow architecture patterns from architecture.md</action>
<action>Run tests after each significant change</action>
<action>Continue until ALL tests pass</action>
</step>

<step n="4" goal="Refactor (REFACTOR)">
<action>Clean up code while keeping tests green</action>
<action>Apply DRY, KISS, YAGNI principles</action>
<action>Run tests one final time</action>
</step>

<step n="5" goal="Request review">
<action>Update sprint-status.yaml: story status → `review`</action>
<action>Delegate to `code-reviewer` for review</action>
<action>Delegate to `qa-engineer` for acceptance testing</action>
</step>

</workflow>
