# Create Pull Request

## Overview

Create a GitHub PR using the template from `.cursor/rules/pr-conventions.mdc`. Supports referencing Sentry issues and Shortcut stories. Automatically pushes branch if not already pushed.

## Steps

1. **Gather Context**
   - Run `git status` to check current state
   - Run `git branch --show-current` to get current branch
   - Run `git diff master` to see changes vs master

2. **Fetch External References**
   - If `--sentry <issue-id>` provided: Fetch Sentry issue using Sentry MCP
   - If `--shortcut <story-id>` provided: Fetch Shortcut story using Shortcut MCP `mcp_shortcut_stories-get-by-id`

3. **Push Branch if Needed**
   - Check if branch is pushed: `git push -u origin $(git branch --show-current)`
   - If not pushed, push the branch

4. **Fill PR Template**
   - Use template from `.cursor/rules/pr-conventions.mdc`
   - Fill all required sections:
     - Summary
     - Type of Change
     - Description (What changed?, Why?, How?)
     - Related Issues (link Sentry/Shortcut if provided)
     - Changes Made
     - Screenshots/Videos (if applicable)
     - QA Instructions (prerequisites, test scenarios)
     - Communications to Stakeholders
     - Deployment Notes
     - Additional Notes
   - Ensure Boxful-specific requirements met:
     - Detailed QA instructions
     - Accurate deployment notes
     - Proper Sentry/Shortcut linking

5. **Create PR**
   - Use GitHub CLI: `gh pr create --title "<title>" --body-file <(echo "$PR_BODY")`
   - Output the URL of the newly created PR

## Checklist

- [ ] Git context gathered
- [ ] External references fetched if provided
- [ ] Branch pushed if needed
- [ ] PR template filled completely
- [ ] QA instructions detailed
- [ ] Deployment notes accurate
- [ ] Sentry/Shortcut issues linked
- [ ] PR created successfully
- [ ] PR URL output for sharing
