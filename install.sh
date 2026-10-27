#!/usr/bin/env bash
# Symlink every skill in this repo into ~/.claude/skills so edits here are live.
set -euo pipefail

src="$(cd "$(dirname "$0")/skills" && pwd)"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$dest"

for dir in "$src"/*/; do
  name="$(basename "$dir")"
  target="$dest/$name"
  if [ -L "$target" ]; then
    rm "$target"
  elif [ -e "$target" ]; then
    mv "$target" "$target.bak.$(date +%s)"
    echo "backed up existing $name"
  fi
  ln -s "${dir%/}" "$target"
  echo "linked $name"
done
