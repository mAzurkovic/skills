# skills

Personal [Claude Code](https://claude.com/claude-code) skills.

## Layout

```
skills/
  <group>/
    <skill-name>/
      SKILL.md      # frontmatter (name, description) + instructions
      ...           # optional scripts, references, assets, examples
install.sh          # symlinks each skill into ~/.claude/skills
```

Groups are for organizing only. Claude Code sees a flat list: folder name = skill name = slash command, so names must be unique across groups.

## Install

```bash
git clone https://github.com/mAzurkovic/skills.git
cd skills && ./install.sh
```

Skills are symlinked, so editing them here updates Claude Code immediately. Existing non-symlink folders with the same name are backed up as `<name>.bak.<timestamp>`. Re-run after adding a new skill.

## Skills

### dev

Spec-driven feature workflow. Each step writes to `./specs/<feature>/`.

Large projects: `/to-brd` → `/to-design` → `/to-milestones` splits the design into milestones in build order in `./specs/<project>/milestones.md`. Then per milestone, in order: `/to-design M<n>` (only if the milestone is complex enough) → `/to-tasks M<n>` → `/implement-feature`. Each milestone's files go in `./specs/<project>/m<n>-<name>/`.

| Skill | Input | Output |
|---|---|---|
| `/to-brd` | idea, blurb, rough doc | `requirements.md` |
| `/to-design` | `requirements.md` | `design.md` |
| `/to-milestones` | large `design.md` | `milestones.md` |
| `/to-tasks` | `design.md` | `tasks.md` |
| `/implement-feature` | `tasks.md` | code + tests, 100% coverage on changes |
| `/pr` | branch diff vs default branch | GitHub PR, description in Simplified Technical English |
| `/verify` | spec + running system | pass or fail per case, from a real deploy and call |
| `/expert-review` | uncommitted changes, branch, or PR | numbered findings: bugs, risks, idiom, lean |

### hardware

KiCad board workflow. Pairs with the `kicad-happy` plugin skills.

| Skill | Input | Output |
|---|---|---|
| `/to-schematic` | `design-electronics.md` | `hw/<board>.kicad_sch`, ERC clean, datasheet check table |
| `/to-layout` | approved schematic | `hw/<board>.kicad_pcb`, DRC clean, fab files on request |
