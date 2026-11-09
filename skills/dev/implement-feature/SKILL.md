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

1. **Read the spec.** Argument: path, feature name, or task ids. Default `./specs/<feature>/tasks.md`. Read the spec files next to it. Feature of a milestone (`./specs/<project>/m<n>-<name>/f<k>-<name>/`): `requirements.md` and `design.md` next to tasks.md exist only if the feature needed them. Also read `../../design.md`, `../../requirements.md`, and the milestone and feature entry in `../../milestones.md`. Run one feature at a time, never a whole milestone. If `progress.md` exists, continue from it.
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
- Remove temp files, sandboxes and processes that you or your tools made. Check before you delete.

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
  Done gate       → fail     → fix tasks. Run the Done gate again.
  /verify         → FAIL     → fix tasks. Run /verify again.
  /expert-review  → Must fix → fix tasks. Run the rechecks in the table.
  all clean       → Ship.
  round limit     → Ship with open findings listed.
  stuck           → Stop and ask.
```

Rechecks after a fix:

| Fix | Recheck |
|-----|---------|
| Spec or doc text only | None. It does not block Ship. |
| Small code fix | Done gate. /verify if behavior changed. |
| Must fix in code, or a large code change | Done gate, /verify, and one /expert-review of that diff only. |

- Run at most 2 /expert-review rounds on a feature. Do not fix the Must fix findings of the second round. List them as open in the Report and the PR, and ship.
- Run at most 3 rounds. After round 3, ship if the Done gate and /verify pass. If not, Stop and ask.
- Do each fix task with the Build loop.
- Stuck means no progress or too many rounds:
  - A fixed failure or finding comes back.
  - The same /verify case fails 2 times in a row.
  - 3 /verify runs have finished and the last one did not pass.
- Start a new subagent for each /verify and each /expert-review, so that each one has a fresh context.
- Each /verify and /expert-review subagent prompt has this line: `Open no visible browser windows. Use headless browsers only. Call no paid or third-party service unless the spec needs it and the user approved it. Do not read or copy secrets files.`
- The /verify subagent gets only: the spec paths, the repo path, any deploy approval from the user, and `Read ~/.claude/skills/verify/SKILL.md and follow it.` On a rerun, also: the case numbers that failed in the last /verify, and the spec items that the fix tasks address. Never give it your notes or claims about the code.
- /verify saves its cases and run script in `verify/` next to tasks.md, and reuses them on reruns. Do not read or change `verify/`. Use only the /verify report.
- The /expert-review subagent gets: the spec paths, the diff to review, the rejected findings from progress.md, and `Read ~/.claude/skills/expert-review/SKILL.md and follow it.` It reviews the diff, and reads more of the code only when it needs the context to understand the diff.
- Fix Must fix findings only. Write all other findings in progress.md as follow-ups, and list them in the Report. They do not block a clean round. Reject a Must fix finding only if it has no real failing case, or it conflicts with the spec or the repo conventions. Write the reason in progress.md. A rejected finding does not block a clean round.
- /verify SKIP is a pass. BLOCKED: Stop and ask. If the user gives approval, run /verify again with it.

## Done gate

All must pass:
- Build.
- Formatter, linter, and type checker, with the repo config.
- Full test suite.
- Every piece of logic and every error path that can fail has a test. Measure line coverage and report it. No percentage is required.
- Leak check.
- All tasks ticked.

## Ship

Conditions. All must be true:
- The Feature loop stopped with these results on the final code:
  - Done gate passed.
  - /verify: PASS on all cases that ran. SKIP is OK. Each `Not verified` item has the user's approval and is in the PR. `Spec gaps` that affect this code: none.
  - /expert-review: no open Must fix findings, except findings rejected with a reason, or left open by the round limits and listed in the PR.
- No test was changed, except tests that progress.md records as wrong against the spec.
- You ran the final code on a real input and have the real output, for the Proof section of /pr. See that skill for the rules.

Questions during the Build loop do not block Ship. If you are not sure, do not ship.

Steps:
1. On the default branch: make the branch `<feature-kebab-name>`. On a feature branch: use it.
2. Stage only the code and tests of this feature. Stage `specs/` only if git already tracks it.
   Never stage `progress.md`, `verify/`, scratch files, or anything else the project does not need.
3. Commit with one STE line, 60 characters max, imperative. Add the commit attribution from the system reminder, if there is one.
4. Run `/pr auto`. Give it the proof command, input, and output.

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
Coverage: <lines %> on changed code. Untested: <file:line, why> | none
Verified: <cases that passed in the last /verify>
Not verified: <cases not run, and why> | none
Review: <n> findings. Fixed: <#s>. Rejected: <#s and why> | none. Follow-ups: <#s> | none
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

- Test all added or changed logic and error paths. Measure line coverage. A percentage is not the goal; untested logic is the problem.
- Use the repo test framework and coverage tool. If there is none: recommend the ecosystem default (pytest-cov, vitest or jest `--coverage`, `go test -cover`, `cargo llvm-cov`, JaCoCo) and ask.
- Test behavior through the public interface. Do not test private internals.
- Each branch and error path has a test that fails if it breaks. A test without a real assertion does not count.
- Use table-driven or parametrized tests if the language prefers them. No duplicate tests. No new fixture frameworks.
- Delete a line that cannot run. An error path that only a rare platform condition can reach may stay untested; name it in the Report.
- Keep the project coverage threshold passing.

## Leak check

Scan the added lines:

```bash
git diff -U0 HEAD | grep '^+' | grep -nE '\b(N?FR|OQ|US|D|M)-?[0-9]+\b|\bF[0-9]+\b|\b[Tt]ask [0-9]+(\.[0-9]+)?\b|requirements\.md|design\.md|milestones\.md|tasks\.md|progress\.md|specs/'
```

Include untracked files: run `git add -N` first. Not a git repo: scan the changed files. Check each hit. Remove each real leak.
