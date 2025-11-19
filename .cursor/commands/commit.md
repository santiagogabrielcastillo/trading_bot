# Git Commit

## Overview

Create a git commit following Conventional Commits format with Boxful-specific conventions. Supports referencing Sentry issues and Shortcut stories. Can amend the last commit if `--amend` is provided.

## Steps

1. **Gather Context**
   - Run `git status` to see current state
   - Run `git diff HEAD` to see staged and unstaged changes
   - Run `git branch --show-current` to get current branch
   - Run `git log --oneline -10` to see recent commits

2. **Fetch External References**
   - If `--shortcut <story-id>` provided: Fetch Shortcut story using Shortcut MCP `mcp_shortcut_stories-get-by-id`
   - If `--sentry <issue-id>` provided: Fetch Sentry issue using Sentry MCP

3. **Create Commit Message**
   - Follow commit conventions from `.cursor/rules/commit-conventions.mdc`
   - Use Conventional Commits format: `<type>[optional scope]: <description>`
   - Include body explaining why, how, side effects, breaking changes
   - Add footers for Sentry issues and Shortcut stories if provided
   - Keep title to 50 characters, wrap body at 72 characters

4. **Execute Commit**
   - If `--amend` provided: Amend last commit with `git commit --amend`
   - Otherwise: Create new commit with `git commit -m "<message>"`
   - Do not add any other files unless explicitly instructed

## Checklist

- [ ] Git status and diff reviewed
- [ ] External references fetched if provided
- [ ] Commit message follows Conventional Commits format
- [ ] Commit message includes Sentry/Shortcut references if provided
- [ ] Commit created or amended as requested
- [ ] No unintended files added to commit
