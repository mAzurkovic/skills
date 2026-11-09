---
name: to-tasks
description: Split a design into a small, ordered task list (max ~5 parents, each with subtasks an agent can execute). Use when user says "/to-tasks", "break this down", or points at a design.md and wants an actionable plan.
---

# /to-tasks

Turn a design into ≤5 parent tasks, each with concrete subtasks.

## Voice

- No em-dashes.
- Fragments fine.
- Concrete: name files, classes, functions, tests.
- No weasel words.
- SHORT.

## Flow

1. **Read design.** Default `./specs/<feature>/design.md`. Also read `requirements.md` if present. Confirm in one line.
   - **Feature of a milestone** (user names one, e.g. "M2 F1", and `milestones.md` exists): the **project dir** holds `milestones.md` and the project `design.md` (e.g. `docs/` or `./specs/<project>/`). Scope is that feature only. Input is its entry in `milestones.md`, the project docs, and the feature's own `requirements.md` and `design.md` if it has them; they win on detail. A feature may have neither: then its entry and the project docs are the input. Features already built: reuse them. Later ones are out of scope: do not build ahead, do not block them. Write to `<project dir>/m<n>-<milestone-kebab-name>/f<k>-<feature-kebab-name>/``tasks.md`.
2. **Read codebase.** Find the actual files, packages, modules each task touches. Never invent paths.
3. **Group into ≤5 parent tasks, by behavior, not by layer.** Each parent is something that runs and can be tested end to end, cutting through whatever layers it needs ("a prompt gets relevant memories", not "storage layer"). Add only the part of a layer that this behavior needs. Order by dependency: blockers first. More than 5 parents: the feature is too big; say so and propose how to split it.
4. **Subtasks: agent-sized.** Each subtask is one focused change. Names a file, a function, a test. Doable in one CR. If a subtask spans multiple files or unclear scope, split it.
5. **Ask one question at a time** only when scope, ordering, or location is genuinely unclear. Provide recommendation with one-line reason.
6. **Never invent.** Unknown file path, class, or test framework: ask or grep first.
7. **List open questions** before writing.
8. **Write tasks** to `./specs/<feature-kebab-name>/tasks.md`. Create dir if missing. Ask before overwriting. Always use `./specs/` even if the project has a `.kiro/specs/` directory or CLAUDE.md mentions one.

Question template:
```
Q: <question>
Recommend: <answer>
Why: <one sentence>
```

## Task Structure

Markdown checkboxes. ≤5 parents. Each parent has 2 to 6 subtasks. Each subtask is one sentence.

```markdown
# <Feature Name> — Tasks

## 1. <Parent task name>
- [ ] 1.1 <subtask>. <file or function>. <acceptance>.
- [ ] 1.2 ...

## 2. <Parent task name>
- [ ] 2.1 ...

## Dependencies
- 2 blocks 3.
- 4 needs 1.1 done.
```

Acceptance per subtask: one short clause. "Returns 200 on valid input." "Test passes." "Migration applied locally."

If the design is too small for 5 parents, use fewer. Do not pad.

## Parallelism for execution

Tag each parent task with `[parallel]` or `[serial]` based on dependencies. Subtasks within a parent run serial by default unless marked `[parallel]`.

When the user says "execute" or "run these tasks":
- Dispatch independent parents concurrently via the Agent tool (one subagent per parent).
- Within a parallel parent, dispatch independent subtasks concurrently too.
- Send all parallel Agent calls in a **single message** with multiple tool uses.
- Block on a `[serial]` task until its dependencies in the Dependencies section are done.
- Each subagent gets: the relevant subtask block, the design.md path, the requirements.md path (plus the milestone's `Covers` ids, if any), and explicit file paths it may touch. Use `isolation: "worktree"` if subagents touch overlapping areas.
- After all subagents return, run the package build once and report failures.

Mark dependencies explicitly so the dispatcher knows what is safe to parallelize:

```markdown
## 1. Create an order and read it back [serial]
## 2. Reject invalid orders [parallel, needs 1]
## 3. List a customer's orders [parallel, needs 1]
```

## Not your job

No code. No estimates. No requirements changes (that is /to-brd). No design changes (that is /to-design).
