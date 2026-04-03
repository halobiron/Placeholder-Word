# Create PRD Workflow

**Goal:** Create a comprehensive Product Requirements Document through guided conversation.

**Your Role:** You are a Product Manager creating a structured PRD. Guide the user through requirements discovery.

---

## INITIALIZATION

### Context Loading
- Load `plans/artifacts/product-brief.md` (if exists) → use as starting context
- Load `plans/artifacts/project-context.md` (if exists) → project conventions
- Check if `plans/artifacts/PRD.md` already exists → if yes, ask user: update or create new?

### Output Path
- PRD file: `plans/artifacts/PRD.md`

---

## EXECUTION

<workflow>

<step n="1" goal="Understand the product vision">
<action>Ask the user about the product/feature they want to build</action>
<action>Identify: target users, problem being solved, key value proposition</action>
<action>If product-brief.md exists, reference it and confirm/update assumptions</action>
</step>

<step n="2" goal="Define user personas and journeys">
<action>Identify 2-3 primary user personas</action>
<action>Map key user journeys for each persona</action>
<action>Validate with user: "Are these the right users and workflows?"</action>
</step>

<step n="3" goal="Define functional requirements">
<action>List all functional requirements organized by feature area</action>
<action>For each requirement: description, priority (P1/P2/P3), acceptance criteria</action>
<action>Use MoSCoW prioritization: Must-have, Should-have, Could-have, Won't-have</action>
</step>

<step n="4" goal="Define non-functional requirements">
<action>Performance requirements (response times, throughput)</action>
<action>Security requirements (auth, data protection)</action>
<action>Scalability, reliability, maintainability requirements</action>
<action>Technology constraints and preferences</action>
</step>

<step n="5" goal="Define success metrics">
<action>Key metrics that indicate product success</action>
<action>How to measure each metric</action>
<action>Target values and timelines</action>
</step>

<step n="6" goal="Generate PRD document">
<action>Create PRD using template from `plans/templates/prd-template.md`</action>
<action>Write to `plans/artifacts/PRD.md`</action>
<action>Display summary to user for approval</action>
</step>

</workflow>

## Post-Completion

After PRD is created:
1. Inform user: "PRD created at `plans/artifacts/PRD.md`"
2. Suggest next step: "Run `/architecture` to create the technical architecture (Phase 3)"
3. Or: "Run `/story create` if architecture already exists"
