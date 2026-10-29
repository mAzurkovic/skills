---
name: to-milestones
description: Split a large, complex design into an ordered set of milestones in logical build order, each small enough for one /to-tasks list. Use when user says "/to-milestones", "break this into milestones", "phase this project", or points at a design.md too big for one task list.
---

# /to-milestones

Turn a large design into ordered milestones. Each milestone is a coherent, verifiable deliverable in the order the system is naturally built, and gets its own /to-tasks list. `milestones.md` is also the project's tracking document: each milestone carries a `Status` (`not started`, `in progress`, `done`), updated as work progresses.

## Voice

- No em-dashes.
- Fragments fine. Sacrifice grammar for conciseness.
- Concrete: name the design's components, not new ones.
- No weasel words: "might", "could", "possibly".
- SHORT.

## Flow

1. **Read the design.** Use the `design.md` the user points at (e.g. `docs/design.md`); default `./specs/<project>/design.md`. Its directory is the **project dir**. Also read `requirements.md` in the project dir. Confirm in one line what you read: component count, requirement count.
2. **Read the codebase** if one exists. What is already built shrinks or removes milestones. State what you found.
3. **Draft the cut.** Propose the milestone list (names + one-line deliverable each) before detailing anything. Rules below.
4. **Never invent.** A milestone needs a component, interface, or requirement the design does not have: record it as an open question. Design gaps go back to /to-design, requirement gaps to /to-brd.
5. **Check coverage.** Every requirement id and every design component lands in a milestone or in Deferred. A component may span milestones (built in stages); say what each milestone adds to it.
6. **Write** `<project dir>/milestones.md`, next to `design.md`. Reference requirement ids and component names; never copy their text. Ask before overwriting. Never use `.kiro/specs/`, even if the project has one or CLAUDE.md mentions it.

## Cutting rules

- **Logical build order.** Cut where development naturally divides: foundations before what sits on them. A layer is a fine milestone ("storage layer", "auth service") when it is coherent and testable on its own.
- **Dependencies first.** A milestone only uses what earlier milestones built. Follow the design's component graph.
- **Riskiest early.** Unproven components, external integrations, and hard performance requirements go in the first milestones that can hold them.
- **Each builds on the last.** Never breaks what an earlier milestone delivered.
- **Verifiable on its own.** Every milestone ends with something checkable: tests passing against a real interface, a running service, a working flow. Not "half the schema".
- **Sized for one task list.** A milestone fits /to-tasks' limit of ~5 parent tasks. Bigger: split it.
- **Up to ~7 milestones.** One is fine when the design is one coherent unit. More than ~7: milestones are too thin, merge.
- **Features are optional.** List them when a milestone delivers several distinct pieces; one or none is fine.
- **Exit criteria are testable.** Derived from the requirements' and design's criteria, not new ones.

## milestones.md Structure

Numbered bullets. No long prose. Drop sections that do not apply.

```markdown
# <Project Name> — Milestones

## M1. <Name>
- Delivers: <what exists and works when done>. One or two lines.
- Builds: <Component> (<what this milestone adds>), <Component> (...).
- Covers: FR1, FR2, NFR3.
- Features:
  - <feature>: <one line>.
- Exit criteria:
  - <testable criterion>
- Needs: none.
- Design: yes.
- Status: not started.

## M2. <Name>
- Delivers: ...
- Builds: ...
- Covers: ...
- Exit criteria: ...
- Needs: M1.
- Status: not started.

## Deferred
- FR9. <why it is not in any milestone>

## Coverage
| Requirement or component | Milestones |
|---|---|
| FR1 | M1 |
| <Component> | M1, M3 |

## Open Questions
- OQ1. <unresolved, owner, by-when>
```

## Downstream

Per milestone, in order, all in `<project dir>/m<n>-<milestone-kebab-name>/`:
1. /to-design M<n>, only when the milestone is complex enough to need its own design. Writes `design.md`.
2. /to-tasks M<n>. Writes `tasks.md`.
3. /implement-feature on that `tasks.md`.

When drafting, flag milestones that likely need their own design (new data model, non-trivial algorithm, multiple interacting components) with `- Design: yes` in their entry.

## Not your job

No requirements rewriting (that is /to-brd). No design changes (that is /to-design). No task breakdown (that is /to-tasks). No estimates or dates.
