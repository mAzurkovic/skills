# skills

Personal [Claude Code](https://claude.com/claude-code) skills.

## Layout

```
skills/
  <skill-name>/
    SKILL.md        # frontmatter (name, description) + instructions
    ...             # optional scripts, references, templates
install.sh          # symlinks each skill into ~/.claude/skills
```

One folder per skill. Folder name = skill name = slash command.

## Install

```bash
git clone https://github.com/mAzurkovic/skills.git
cd skills && ./install.sh
```

Skills are symlinked, so editing them here updates Claude Code immediately. Existing non-symlink folders with the same name are backed up as `<name>.bak.<timestamp>`. Re-run after adding a new skill.

## Skills

Spec-driven feature workflow. Each step writes to `./specs/<feature>/`.

| Skill | Input | Output |
|---|---|---|
| `/to-brd` | idea, blurb, rough doc | `requirements.md` |
| `/to-design` | `requirements.md` | `design.md` |
| `/to-tasks` | `design.md` | `tasks.md` |
| `/implement-feature` | `tasks.md` | code + tests, 100% coverage on changes |
