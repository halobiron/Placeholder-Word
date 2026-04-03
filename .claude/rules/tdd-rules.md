# TDD Rules

Test-Driven Development is mandatory for all story implementations.

## Core Rules

1. **Test Plan First** — QA Engineer writes test plan BEFORE dev starts
   - Path: `tests/plans/story-{slug}-test-plan.md`
   - Content: test scenarios, edge cases, acceptance criteria mapping
   - **Gate:** Dev cannot start implementing without a test plan

2. **Write Failing Tests (RED)** — Dev writes tests that fail before implementing
   - Tests should match test plan scenarios
   - Running tests confirms they fail (validates test correctness)

3. **Implement (GREEN)** — Dev writes code to make tests pass
   - Only write enough code to pass the tests
   - Run tests frequently during implementation

4. **Refactor** — Clean up while keeping tests green
   - Apply KISS, DRY, YAGNI
   - Run full test suite after refactoring

## Coverage Targets

| Code Type | Minimum Coverage |
|-----------|-----------------|
| Business logic | 80% |
| API handlers | 70% |
| Utility functions | 90% |
| UI components | 60% |

## Test Tiers

1. **Unit Tests** — test individual functions/methods in isolation
2. **Integration Tests** — test component interactions, API endpoints
3. **E2E Tests** — test full user journeys (when applicable)
4. **Acceptance Tests** — directly map to story acceptance criteria

## Acceptance Criteria Mapping

Every acceptance criterion in a story file must have a corresponding test:

```
Story AC: "User can log in with email and password"
→ Test: test_login_with_valid_email_password()
→ Test: test_login_with_invalid_password_fails()
→ Test: test_login_with_nonexistent_email_fails()
```

## When TDD is NOT Required

- Documentation changes (markdown files)
- Configuration changes (env, yaml, json)
- CI/CD pipeline changes
- Refactoring with existing test coverage (if tests still pass)

## Enforcement

- `qa-engineer` agent creates test plans
- `tester` agent runs test suites
- `code-reviewer` agent verifies test coverage
- `agile-gates.md` Gate G4 blocks dev without test plan
