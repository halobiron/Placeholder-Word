# Create Architecture Workflow

**Goal:** Create a comprehensive architecture document based on the PRD.

**Your Role:** You are a System Architect designing the technical solution. The PRD defines WHAT — you define HOW.

---

## INITIALIZATION

### Context Loading (MANDATORY)
- Load `plans/artifacts/PRD.md` → **REQUIRED** — if not found, STOP and tell user to create PRD first
- Load `plans/artifacts/project-context.md` (if exists) → project conventions and tech preferences
- Check if `plans/artifacts/architecture.md` already exists → if yes, ask user: update or create new?

### Output Path
- Architecture file: `plans/artifacts/architecture.md`
- ADR files: `docs/adr/adr-{NNN}-{slug}.md` (as needed)

---

## EXECUTION

<workflow>

<step n="1" goal="Analyze PRD requirements">
<action>Read PRD.md thoroughly — extract all functional and non-functional requirements</action>
<action>Identify: system boundaries, integration points, data entities, user flows</action>
<action>List technical challenges and constraints from PRD</action>
</step>

<step n="2" goal="Define technology stack">
<action>Propose technology stack based on requirements and project-context.md preferences</action>
<action>For each technology choice: rationale, alternatives considered, trade-offs</action>
<action>Create ADR for significant technology decisions</action>
<action>Validate with user: "Does this tech stack align with your preferences?"</action>
</step>

<step n="3" goal="Design component architecture">
<action>Define major system components and their responsibilities</action>
<action>Define component interfaces and communication patterns</action>
<action>Create component diagram (Mermaid syntax)</action>
<action>Define data flow between components</action>
</step>

<step n="4" goal="Design data model">
<action>Define data entities and their relationships</action>
<action>Create ER diagram (Mermaid syntax)</action>
<action>Define storage strategy (DB type, schema approach)</action>
<action>Address data migration and seeding strategy</action>
</step>

<step n="5" goal="Define API contracts">
<action>Define API endpoints, request/response formats</action>
<action>Authentication and authorization strategy</action>
<action>Error handling patterns</action>
<action>Versioning strategy</action>
</step>

<step n="6" goal="Address non-functional requirements">
<action>Performance strategy (caching, optimization)</action>
<action>Security architecture (auth, encryption, input validation)</action>
<action>Scalability approach (horizontal/vertical, load balancing)</action>
<action>Monitoring and observability</action>
</step>

<step n="7" goal="Generate architecture document">
<action>Create architecture doc using template from `plans/templates/architecture-template.md`</action>
<action>Write to `plans/artifacts/architecture.md`</action>
<action>Write any ADRs to `docs/adr/`</action>
<action>Display summary to user for approval</action>
</step>

</workflow>

## Post-Completion

After architecture is created:
1. Inform user: "Architecture created at `plans/artifacts/architecture.md`"
2. Suggest next step: "Run `/story create` to break down into implementable stories"
3. Or: "Run `/readiness-check` to validate cohesion across PRD and architecture"
