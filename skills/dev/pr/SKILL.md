---
name: pr
description: Open a pull request for the current branch with a short description in ASD-STE100 Simplified Technical English (Purpose, Key Changes, Testing). Use when user says "/pr", "make a PR", "open a PR", or wants to merge a piece of code.
argument-hint: "[auto]"
---

# /pr

Open a PR for the current branch. Description in STE. AS SHORT AS POSSIBLE.

## Voice: ASD-STE100 Simplified Technical English

Apply to title and all sections.

- Max 20 words per sentence. Aim for less.
- One topic per sentence.
- Active voice. Present or simple past tense.
- Imperative for instructions ("Run the tests.").
- One word, one meaning. Same term for the same thing every time.
- Use approved simple verbs: add, remove, change, make, use, show, do, get, set, put, start, stop, move, find, keep, give. Not "leverage", "utilize", "facilitate", "ensure", "refactor" when a simple verb works.
- Articles ("the", "a") where they help clarity. No slang, no idioms, no filler.
- Technical names (files, functions, flags) are allowed as-is, in backticks.
- No em-dashes. No adverbs like "simply", "just", "basically".
- If a sentence adds nothing, delete it.

## Flow

1. **Check state.** `git status`, current branch, default branch (`gh repo view --json defaultBranchRef`). If on the default branch, stop and ask for a branch name. If uncommitted changes exist, ask: commit them or leave them.
2. **Read the diff.** `git log <base>..HEAD` and `git diff <base>...HEAD`. Read changed files where the diff is unclear. Never guess what the code does.
3. **Find test evidence.** Look for tests added or changed in the diff. Run the project test command if it is fast and known. Use real results only. If no verification exists, say so in Testing. Never invent results.
4. **Push.** `git push -u origin <branch>` if the branch has no upstream or is ahead.
5. **Draft.** Title: imperative, max 60 chars, STE. Body: template below.
6. **Show the draft** to the user. Wait for approval or edits.
7. **Create.** `gh pr create --title ... --body-file <tmp file>`. Return the PR URL.

**`auto` argument** (from /implement-feature after all its Ship conditions hold): skip the uncommitted-changes question in step 1 and the approval wait in step 6. Print the draft, then create. Still stop on the default branch, a failed push, or a missing `gh` login.

## Template

```markdown
# Purpose
<1-2 sentences. The problem and why this PR solves it.>

# Key Changes
- <HIGH IMPACT or LARGE changes only. One line each. Max ~5.>

# Testing
- <How it was tested.>
- <Verification: command run, result, count of tests passed, manual check done.>
```

## Rules

- Key Changes: skip small edits, renames, formatting, typo fixes, lockfile changes. If only one change matters, list one.
- Testing: state the command and the result (e.g. "`npm test`: 142 pass, 0 fail."). Not "tested locally".
- No extra sections. No headings beyond the three.
- No restating the diff line by line.
- End the body with the attribution line from the system reminder, if present.
