---
name: implement-feature
description: Implement a task list (e.g. ./specs/<feature>/tasks.md from /to-tasks) as minimal, idiomatic, expert-level code with 100% test coverage, then verify it live, review it, fix until clean, and raise a PR. Use when user says "/implement-feature", "implement these tasks", "execute tasks.md", or hands over a task list to build.
argument-hint: "[tasks.md path | feature name | task ids]"
---

# /implement-feature

Make a task list into working, tested code. Write it as an expert in the language writes it. Add nothing extra.

## Terms

- **Spec:** tasks.md, design.md, requirements.md. For a milestone, also its entry in milestones.md.
- **Task:** one checkbox item in tasks.md.
- **Fix task:** a task that the Feature loop adds. Id `F<n>`. It is in progress.md, not in tasks.md.
- **Round:** one pass of the Feature loop.

## Flow

1. **Read the spec.** Argument: path, feature name, or task ids. Default `./specs/<feature>/tasks.md`. Read the spec files next to it. Milestone (`./specs/<project>/m<n>-<name>/`): also read `../design.md`, `../requirements.md`, and its entry in `../milestones.md`. If `progress.md` exists, continue from it.
2. **Read the code.** Find the language, version, framework, and tools: build, format, lint, types, tests, coverage. Read CLAUDE.md, the tool configs, and 2 or 3 files near the change. Follow the data flow from start to end.
3. **Build.** Do each task with the Build loop, in dependency order. Obey `[parallel]` and `[serial, needs N]`.
   - Parallel parents: one subagent each, all in one message. Use `isolation: "worktree"` if they change the same files.
   - Each subagent prompt has: its tasks, the spec paths, the files it can change, and this line: `Read ~/.claude/skills/implement-feature/SKILL.md. Follow Rules, Build loop, Code, and Tests. If you must stop, send the report to me. Do not ask the user.`
   - Few tasks, or tasks that depend on each other: do them yourself.
4. **Check.** Run the Feature loop until it stops.
5. **Ship.** If all Ship conditions are true, make a PR. If not, do not.
6. **Report.**

## Rules

- Do not guess a path, API, or version. If a task is not clear, conflicts with the code, or needs a new dependency: ask one question.
  ```
  Q: <question>
  Recommend: <answer>
  Why: <one sentence>
  ```
- Do not commit, push, or add dependencies. Exception: the Ship steps.
- Do not change the spec. Requirements: /to-brd. Design: /to-design. Tasks: /to-tasks.
- Print a progress line at each step. See Progress.

## Build loop (one task)

```
attempt = 0
loop:
  write the test. Run it. It must fail because the behavior is missing.
  write the code.
  run the task's tests, lint, and type check.
  pass             → tick the task. Next task.
  fail             → attempt += 1. Write the failure in progress.md.
  same failure 2x  → use a different approach.
  attempt = 3      → Stop and ask.
```

Read the error before each attempt. Fix the cause, not the symptom.

### Correct code, not test-passing code

The goal is correct behavior for all valid inputs. Passing tests is only evidence.

- Get each test from the spec. Get expected values from the spec or by hand. Never copy them from the code output.
- The code must be correct for inputs that the tests do not use. Do not special-case test inputs. Do not hardcode expected outputs. Do not detect a test run.
- Do not change a test to match the code. Change a test only if it is wrong against the spec. Write the test name and the reason in progress.md.
- Do not weaken an assertion, widen a tolerance, delete or skip a case, or loosen a type to get a pass.
- Do not mock the unit under test or code you own. Mock only external boundaries: network, clock, slow filesystem.
- Do not discard the error that a test checks. Do not use sleeps or retries to hide a failure.
- Before you tick a task, ask: "If I delete the tests, is this code still correct?" If no, the task is not done.

## Feature loop (whole feature)

```
loop:
  Done gate       → fail     → fix tasks. Next round.
  /verify         → FAIL     → fix tasks. Next round.
  /expert-review  → findings → fix tasks. Next round.
  all clean       → Ship.
  stuck           → Stop and ask.
```

- A round is clean only if all three are clean in that round. After a fix, the next round runs all three again. This proves that the fix broke nothing.
- Do each fix task with the Build loop.
- There is no round limit. Stuck means no progress:
  - A fixed failure or finding comes back.
  - The same /verify case fails in 2 rounds in a row.
  - The number of fix tasks does not decrease for 2 rounds in a row.
  - 10 rounds. This is a safety limit.
- Start a new subagent for /verify and for /expert-review in each round.
- The /verify subagent gets only: the spec paths, the repo path, any deploy approval from the user, and `Read ~/.claude/skills/verify/SKILL.md and follow it.` Never give it your notes or claims about the code.
- The /expert-review subagent gets: the spec paths, what to review, the rejected findings from progress.md, and `Read ~/.claude/skills/expert-review/SKILL.md and follow it.`
- Fix all findings, Nice to have also. Reject a finding only if it has no real failing case, or it conflicts with the spec or the repo conventions. Write the reason in progress.md. A rejected finding does not block a clean round.
- /verify SKIP is a pass. BLOCKED: Stop and ask. If the user gives approval, run /verify again with it.

## Done gate

All must pass:
- Build.
- Formatter, linter, and type checker, with the repo config.
- Full test suite.
- 100% line and branch coverage on changed code.
- Leak check.
- All tasks ticked.

## Ship

Conditions. All must be true:
- The Feature loop stopped on a clean round. In that round:
  - Done gate passed. No coverage pragmas were added.
  - /verify: PASS on all cases. `Not verified: none`. `Spec gaps: none`. SKIP is OK.
  - /expert-review: no findings, except findings rejected with a reason.
- No test was changed, except tests that progress.md records as wrong against the spec.

Questions during the Build loop do not block Ship. If you are not sure, do not ship.

Steps:
1. On the default branch: make the branch `<feature-kebab-name>`. On a feature branch: use it.
2. Stage only the code and tests of this feature. Stage `specs/` only if git already tracks it.
3. Commit with one STE line, 60 characters max, imperative. Add the commit attribution from the system reminder, if there is one.
4. Run `/pr auto`.

## Stop and ask

Stop. Send one block: what you tried, the last failure, your recommendation. Wait for the user.

Stop when:
- A task failed 3 attempts.
- The Feature loop is stuck.
- /verify finds a spec gap, or the spec conflicts with the code. Recommend /to-design. Do not hide the gap in code.
- A fix needs a new dependency, a deploy to a real cloud account, or a change outside the scope.
- /verify is BLOCKED.

## progress.md

Put it next to tasks.md. Make it on the first run. Update it after each attempt and each round. Read it first at each start.

```
# Progress
Round: 2

| Task | Status | Attempts | Last failure |
|------|--------|----------|--------------|
| 1.2 | fail | 2 | POST /orders → 500 on missing customer_id |
| F1  | done | 1 | verify #2: missing customer_id → 500 |
| F2  | todo | 0 | review #3: N+1 query in list_orders |

Changed tests:
- test_total_includes_tax: expected 110, spec says 108.

Rejected findings:
- review #5 "use a dataclass": conflicts with repo convention (TypedDict).
```

## Progress

Print one line at each step and each loop event. No paragraphs. Print subagent results when they return.

```
[read] tasks.md: 4 parents, 11 tasks. Continue at 2.1.
[build 2.1] attempt 1: FAIL: test_rejects_expired_token, KeyError 'exp'
[build 2.1] attempt 2: PASS
[build 2.2] same failure 2x. New approach: <one phrase>
[feature r1] done gate: PASS. verify: FAIL 1 of 6 (missing customer_id → 500, want 400). Add F1.
[feature r2] done gate: PASS. verify: PASS 6 of 6. review: 4 findings. Add F2 to F5.
[feature r3] done gate: PASS. verify: PASS 6 of 6. review: clean.
[ship] PR: <url>
[stop] 1.3 failed 3 attempts. Last: <failure>. Recommend: <...>
```

## Report

One line each. Nothing else.

```
Built: <what>
Coverage: <lines %>, <branches %> on changed code. Pragmas: <file:line, why> | none
Verified: <cases that passed in the last /verify>
Not verified: <cases not run, and why> | none
Review: <n> findings. Fixed: <#s>. Rejected: <#s and why> | none
Rounds: <n>
Skipped: <what, and when to add it> | none
Open issues: <...> | none
PR: <url> | not raised: <condition that failed>
```

## Code

Write as an expert in this language and its ecosystem writes.

- Use the idioms of the language and version: types, error model, names, module layout.
- Repo conventions first. Then the community standard: PEP 8, Effective Go, Rust API Guidelines, the framework docs.
- Use precise types. No `any`, untyped dicts, or strings for structured values.
- Use domain names. One job for each function.
- Handle an error where you can. If not, propagate it. Never discard it.
- Comment only a "why" that the code cannot show. No commented-out code. No TODOs.

### Minimal

Understand the problem first. Then use the first step that works:
1. Not needed for the task? Do not write it.
2. In the codebase? Use it.
3. In the standard library? Use it.
4. A platform feature? Use it: `<input type="date">`, CSS not JS, a DB constraint not app code.
5. In an installed dependency? Use it. Do not add a dependency for a few lines.
6. Can it be one line? Write one line.
7. If not: the minimum code that works.

- No abstraction that the task does not need: no interface with one implementation, no factory for one product, no config for a fixed value.
- No boilerplate. No code "for later".
- Delete before you add. Simple before clever. Fewest files. Smallest diff.
- Two options of the same size: use the one that is correct on edge cases.
- Bug in shared code: fix it once, in the shared function.
- A known limit (global lock, O(n²) scan): one comment with the limit and the upgrade path.
- Never cut: input validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything the task asks for.

### No spec leaks

The code must look as if the spec does not exist. Do not put these in code, tests, comments, names, file names, logs, or error messages:
- Ids: `FR1`, `NFR2`, `D3`, `OQ1`, `US-4`, `M2`, `F2`.
- Task numbers: `1.2`, `task 3`, `step 4`.
- Spec words: `specs/`, `requirements.md`, `design.md`, `milestones.md`, `tasks.md`, `progress.md`, "per the design", "as required by".

Name tests for behavior: `test_rejects_expired_token`, not `test_fr3`.

## Tests

- 100% line and branch coverage on all added or changed lines. Measure it.
- Use the repo test framework and coverage tool. If there is none: recommend the ecosystem default (pytest-cov, vitest or jest `--coverage`, `go test -cover`, `cargo llvm-cov`, JaCoCo) and ask.
- Test behavior through the public interface. Do not test private internals.
- Each branch and error path has a test that fails if it breaks. A test without a real assertion does not count.
- Use table-driven or parametrized tests if the language prefers them. No duplicate tests. No new fixture frameworks.
- A line you cannot cover must not exist. Delete it. Use a coverage pragma only for unreachable platform code.
- Keep the project coverage threshold passing.

## Leak check

Scan the added lines:

```bash
git diff -U0 HEAD | grep '^+' | grep -nE '\b(N?FR|OQ|US|D|M)-?[0-9]+\b|\bF[0-9]+\b|\b[Tt]ask [0-9]+(\.[0-9]+)?\b|requirements\.md|design\.md|milestones\.md|tasks\.md|progress\.md|specs/'
```

Include untracked files: run `git add -N` first. Not a git repo: scan the changed files. Check each hit. Remove each real leak.
