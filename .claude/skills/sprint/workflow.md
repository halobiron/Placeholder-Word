# Sprint Planning & Status Workflow

**Goal:** Generate sprint status tracking from epics and stories. Detect current story statuses and build/update sprint-status.yaml.

**Your Role:** You are a Scrum Master generating and maintaining sprint tracking. Sprint duration: **1 week**.

---

## INITIALIZATION

### Context Loading
- Load all epic files from `plans/epics/epic-*.md`
- Load all story files from `plans/stories/story-*.md`
- Load existing `plans/sprints/sprint-status.yaml` (if exists — preserve advanced statuses)
- Load `plans/artifacts/project-context.md` (if exists)

### Output Path
- Sprint status: `plans/sprints/sprint-status.yaml`

---

## COMMANDS

### `/sprint plan` — Create or Update Sprint

<workflow>

<step n="1" goal="Parse epic and story files">
<action>Find all files matching `plans/epics/epic-*.md`</action>
<action>For each epic, extract story references</action>
<action>Find all story files in `plans/stories/story-*.md`</action>
<action>Build complete inventory of epics and stories</action>
</step>

<step n="2" goal="Build sprint status structure">
<action>For each epic, create entries in order: epic entry → story entries → retrospective entry</action>
<action>Default status: backlog for new items</action>
<action>If story file exists → upgrade to at least `ready-for-dev`</action>
<action>Never downgrade existing statuses</action>
</step>

<step n="3" goal="Generate sprint-status.yaml">

```yaml
# Sprint Status — AgentKit
# generated: {date}
# last_updated: {date}
# sprint_duration: 1 week

# STATUS FLOW:
# Epic:  backlog → in-progress → done
# Story: backlog → ready-for-dev → in-progress → review → done
# Retro: optional → done

development_status:
  # epic-{slug}: status
  # story-{slug}: status
  # epic-{slug}-retrospective: optional
```

<action>Write to plans/sprints/sprint-status.yaml</action>
</step>

<step n="4" goal="Display summary">
<action>Total epics, total stories, in-progress count, done count</action>
<action>Suggest next step: "Use `/story dev {slug}` to start implementing"</action>
</step>

</workflow>

### `/sprint status` — View Current Sprint

1. Read `plans/sprints/sprint-status.yaml`
2. Display formatted status table:
   - 📋 Total stories
   - 🔄 In progress
   - ✅ Done
   - 🚫 Blocked
3. Highlight next recommended action
