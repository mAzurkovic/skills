---
name: to-milestones
description: Split a large BRD, PRD, or requirements doc into an ordered set of demoable milestones, each grouping features that go through /to-design on their own. Use when user says "/to-milestones", "break this into milestones", "phase this project", or hands over requirements too big for one design.
---

# /to-milestones

Turn a large requirements doc into ordered milestones. Each milestone is a deliverable you can demo end to end.

## Voice

- No em-dashes.
- Fragments fine. Sacrifice grammar for conciseness.
- Concrete: name the actor, the action, what the audience sees.
- No weasel words: "might", "could", "possibly".
- SHORT.

## Flow

1. **Read the requirements.** Default `./specs/<project>/requirements.md`. Pasted BRD, PRD, or any doc works too. Confirm in one line what you read and how many requirements it has.
2. **Read the codebase** if one exists. What is already built shrinks or removes milestones. State what you found.
3. **Draft the cut.** Propose the milestone list (names + one-line demo each) before detailing anything. Rules below.
4. **Ask one question at a time** about ordering, scope, or where to cut. Provide your recommended answer with one-line reasoning.
5. **Never invent requirements.** A milestone needs something the doc does not state: ask, or record as an open question. Requirement gaps go back to /to-brd.
6. **Check coverage.** Every requirement id lands in exactly one milestone or in Deferred. No orphans, no duplicates.
7. **List open questions** before writing. User resolves or accepts as TBD.
8. **Write** `./specs/<project>/milestones.md`, next to the project's `requirements.md`. Features reference requirement ids; never copy requirement text. Create dir if missing. Ask before overwriting. Always use `./specs/` even if the project has a `.kiro/specs/` directory or CLAUDE.md mentions one.

Question template:
```
Q: <question>
Recommend: <answer>
Why: <one sentence>
```

## Cutting rules

- **Demoable.** Every milestone ends in something a stakeholder watches working: a user flow, not a layer. "Schema done" is not a milestone.
- **Vertical slices.** Each milestone cuts through every layer it needs, thin. Not "backend milestone, then frontend milestone".
- **M1 is the walking skeleton.** Thinnest end-to-end path through the system, real deployment if the project has one.
- **Riskiest early.** Unknown tech, external integrations, and hard performance requirements go in the first milestones that can hold them.
- **Each builds on the last.** Never breaks an earlier milestone's demo.
- **3 to 7 milestones.** Fewer: the project is small, use /to-design directly. More: milestones are too thin, merge.
- **1 to 4 features per milestone.** A feature is one /to-design unit: one coherent design doc, one tasks.md.
- **Exit criteria are testable.** Derived from the requirements' success criteria, not new ones.

## milestones.md Structure

Numbered bullets. No long prose. Drop sections that do not apply.

```markdown
# <Project Name> — Milestones

## M1. <Name>
- Demo: <who> does <what>, sees <result>. 2 to 4 steps.
- Features:
  - <feature-kebab-name>: <one line>. Covers FR1, FR2, NFR3.
- Exit criteria:
  - <testable criterion from the requirements>
- Needs: none.

## M2. <Name>
- Demo: ...
- Features: ...
- Exit criteria: ...
- Needs: M1.

## Deferred
- FR9. <why it is not in any milestone>

## Coverage
| Requirement | Milestone | Feature |
|---|---|---|
| FR1 | M1 | <feature> |

## Open Questions
- OQ1. <unresolved, owner, by-when>
```

## Downstream

Each feature's design, tasks, and code live in `./specs/<project>/<feature-kebab-name>/`. /to-design, /to-tasks, and /implement-feature read the feature's scope from `milestones.md`: its `Covers` ids from the project's `requirements.md`. Feature names must be unique across milestones.

## Not your job

No requirements rewriting (that is /to-brd). No architecture (that is /to-design). No task breakdown (that is /to-tasks). No estimates or dates.
