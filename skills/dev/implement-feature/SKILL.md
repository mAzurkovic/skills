---
name: implement-feature
description: Implement a task list (e.g. ./specs/<feature>/tasks.md from /to-tasks) as minimal, idiomatic, expert-level code with 100% test coverage and no spec references leaking into the code. Use when user says "/implement-feature", "implement these tasks", "execute tasks.md", or hands over a task list to build.
argument-hint: "[tasks.md path | feature name | task ids]"
---

# /implement-feature

Turn a task list into working, tested code. Written as the best expert in the language would write it. Nothing extra.

## Voice

- No em-dashes.
- Fragments fine.
- SHORT. Code speaks; prose does not defend it.

## Flow

1. **Read the tasks.** Argument is a path, feature name, or task ids. Default `./specs/<feature>/tasks.md`. Pasted list works too. Also read `design.md` and `requirements.md` alongside it if present. Milestone (`./specs/<project>/m<n>-<name>/tasks.md`): read `../design.md`, `../requirements.md`, the milestone's entry in `../milestones.md`, and the milestone's own `design.md` if present. Confirm in one line what you read and which tasks you will run.
2. **Read the codebase before writing.** Language, version, framework, build tool, formatter, linter, type checker, test runner, coverage tool. Read CLAUDE.md, lint and format configs, and 2 or 3 neighboring files the change touches. Trace the real flow end to end. Match what is there.
3. **Ask one question at a time** only when a task is ambiguous, contradicts the codebase, or needs a new dependency. Never guess a path, API, or library version.
   ```
   Q: <question>
   Recommend: <answer>
   Why: <one sentence>
   ```
4. **Execute in dependency order.** Honor `[parallel]` / `[serial, needs N]` tags and the Dependencies section.
   - Parallel parents: one Agent call per parent, all in a **single message**. Use `isolation: "worktree"` when they touch overlapping files.
   - Every subagent prompt includes: its subtask block, the design and requirements paths, the files it may touch, and this line verbatim: `Read ~/.claude/skills/implement-feature/SKILL.md and follow its Standards, Tests, and Leak check sections exactly.`
   - Small list or tightly coupled tasks: do them inline, no subagents.
5. **Per subtask:** write the test and the code, run the tests, tick `- [x]` in tasks.md.
6. **Finish:** run the full Done gate below once everything is merged in. Fix failures before reporting.
7. **Report** in at most five lines: what was built, coverage result, anything skipped and when to add it, open issues.

Do not commit, push, or add dependencies unless the user says so.

## Standards

### Write it like the expert

Code must read as if written by a recognized expert in that language and its ecosystem. Not a generalist translating from another language.

- Idiomatic for the language and version in use: its type system, error model, naming, module layout, and standard idioms. Pythonic Python, idiomatic Go, idiomatic Rust, modern TypeScript. No Java-isms in Python, no exceptions-as-control-flow in Go.
- Follow the community standard where the repo is silent: PEP 8 / typing, Effective Go, Rust API Guidelines, the framework's own documented conventions.
- Repo conventions beat community conventions. Consistency with surrounding code wins.
- Precise types. No `any`, untyped dicts, or stringly-typed values where the language offers better.
- Names say what things are in domain terms. Short functions, one job each.
- Errors handled where they can be handled, propagated idiomatically otherwise. Never swallowed.
- Comments only for a non-obvious *why*. Never restate the code. No commented-out code, no TODO scaffolding.

### Minimal (the ladder)

Understand the problem first, then stop at the first rung that holds:

1. Does this need to exist? Not required by the task: skip it.
2. Already in this codebase? Reuse the helper, type, or pattern.
3. Stdlib does it? Use it.
4. Native platform feature covers it? Use it (`<input type="date">`, CSS over JS, DB constraint over app code).
5. Already-installed dependency solves it? Use it. Never add one for what a few lines can do.
6. Can it be one line? One line.
7. Only then: the minimum code that works.

Rules:
- No unrequested abstractions: no interface with one implementation, no factory for one product, no config for a value that never changes.
- No boilerplate, no scaffolding "for later".
- Deletion over addition. Boring over clever. Fewest files. Shortest working diff, in the right place.
- Two options the same size: take the one correct on edge cases.
- Bug in shared code: fix the root cause once in the shared function, not in each caller.
- A deliberate simplification with a known ceiling (global lock, O(n²) scan) gets one plain comment naming the ceiling and the upgrade path.

Never cut: input validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything the task explicitly asks for.

### No spec leakage

The spec is scaffolding for you, not part of the product. Code must read as if the spec never existed.

Never put any of these in source, tests, comments, docstrings, identifiers, file names, log lines, or error messages:
- Requirement or decision ids: `FR1`, `NFR2`, `D3`, `OQ1`, `US-4`, milestone ids `M2`, or any similar encoding.
- Task numbers: `1.2`, `task 3`, `step 4`.
- Spec paths or words: `specs/`, `requirements.md`, `design.md`, `milestones.md`, `tasks.md`, "per the design", "as required by".

Name tests and code after behavior: `test_rejects_expired_token`, not `test_fr3`.

## Tests

**100% line and branch coverage of every line the feature adds or changes.** Measured, not estimated.

- Use the project's existing test framework and coverage tool. None configured: use the ecosystem default (pytest + pytest-cov, vitest/jest `--coverage`, `go test -cover`, `cargo llvm-cov`, JaCoCo) and ask before adding it.
- Test behavior through the public interface. No asserting on private internals, no mocking what you own. Mock only true boundaries (network, clock, filesystem when slow).
- Every branch and error path gets a case that fails if it breaks. A test with no meaningful assertion does not count.
- Idiomatic and minimal: table-driven / parametrized cases where the language favors them. No duplicate tests, no fixture frameworks the repo does not already use.
- A line you cannot cover is a line that should not exist. Delete it before reaching for an exclusion. Coverage-ignore pragmas only for genuinely unreachable platform code, and call each one out in the report.
- Keep any existing project-wide coverage threshold passing.

## Leak check

Before reporting, scan added lines:

```bash
git diff -U0 HEAD | grep '^+' | grep -nE '\b(N?FR|OQ|US|D|M)-?[0-9]+\b|\b[Tt]ask [0-9]+(\.[0-9]+)?\b|requirements\.md|design\.md|milestones\.md|tasks\.md|specs/'
```

Not a git repo: run the same pattern over the touched files. Review each hit; remove every real leak. Also include untracked new files (`git add -N` first or grep them directly).

## Done gate

All must pass:
- Build succeeds.
- Formatter, linter, and type checker clean with the repo's config.
- Full test suite passes.
- Coverage report shows 100% lines and branches on changed code.
- Leak check clean.
- Every executed subtask ticked in tasks.md.

## Not your job

No requirements changes (that is /to-brd). No design changes (that is /to-design). No re-planning tasks (that is /to-tasks). A task that is wrong or impossible: stop and ask.
