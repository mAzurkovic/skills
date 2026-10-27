---
name: to-brd
description: Turn a blurb or rough doc into an unambiguous Business Requirements Document (BRD) through one-question-at-a-time clarification. Use when the user says "/to-brd", "make this a BRD", "spec this out", or hands you a feature idea that needs requirements pinned down.
---

# /to-brd

Turn a rough idea into precise business requirements.

## Voice

- No em-dashes.
- Sacrifice grammar for conciseness. Fragments fine.
- Concrete over abstract. "P99 under 200ms" not "fast".
- No weasel words: "might", "could", "possibly", "generally".

Apply to questions, recommendations, and final BRD.

## Flow

1. **Read what user gave you.** Text, file, link, code. Never ask what the source already answers.
2. **Ask one question at a time.** Single focused question. Wait for answer. Provide your recommended answer with one-line reasoning. User confirms or corrects.
3. **Explore instead of asking.** If the codebase or a doc can answer, go look. State what you found, then ask only what is still unclear.
4. **Depth-first.** Follow each branch to resolution before returning.
5. **Stop when every requirement is testable, every actor named, every failure mode enumerated, every success criterion quantified.**
6. **List remaining open questions** before writing. User resolves or accepts as TBD.
7. **Write the BRD** to `./specs/<feature-kebab-name>/requirements.md`. Create dir if missing. Ask before overwriting. Always use `./specs/` even if the project has a `.kiro/specs/` directory or CLAUDE.md mentions one.

Question template:
```
Q: <question>
Recommend: <answer>
Why: <one sentence>
```

## BRD Structure

Numbered bullets. No long prose. Drop sections that do not apply.

```markdown
# <Feature Name> — Requirements

## User Stories
- As <role>, I want <goal>, so <benefit>.

## Functional Requirements
- FR1. <trigger>: <system response>. <success criterion>.
- FR2. ...

## Non-Functional Requirements
- NFR1. Performance: <metric, threshold>
- NFR2. Scale: <volume, rate>
- NFR3. Availability: <SLO>
- NFR4. Security: <auth, data handling>

## Out of Scope
- <explicitly excluded>

## Open Questions
- OQ1. <unresolved, owner, by-when>
```

Include user stories only when actors and goals are not obvious from the FRs.

## Not your job

No architecture, tech stack, estimates, or schedules. Requirements only.
