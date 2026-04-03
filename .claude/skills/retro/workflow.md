# Sprint Retrospective Workflow

**Goal:** Summarize sprint outcomes, capture lessons learned, identify improvements.

**Your Role:** You are a Scrum Master facilitating a retrospective.

## Context Loading
- Load `plans/sprints/sprint-status.yaml` → current sprint state
- Load completed story files from `plans/stories/`
- Load any reports from `plans/reports/`

## Process

1. **Gather Data**
   - Stories completed vs planned
   - Stories rolled over (not done)
   - Blockers encountered and how they were resolved

2. **Generate Insights**
   - What went well?
   - What didn't go well?
   - What should we improve?

3. **Action Items**
   - Concrete improvements for next sprint
   - Process changes to implement

4. **Write Retro Report**
   - Output: `plans/sprints/sprint-{n}-retro.md`
   - Format:

```markdown
# Sprint {n} Retrospective
Date: {date}

## Summary
- Stories planned: {count}
- Stories completed: {count}
- Stories rolled over: {list}

## What Went Well
- {items}

## What Didn't Go Well
- {items}

## Action Items for Next Sprint
- [ ] {improvement 1}
- [ ] {improvement 2}
```

5. **Suggest Next Steps**
   - "Run `/sprint plan` to start the next sprint"
   - "Roll over incomplete stories automatically? (y/n)"
