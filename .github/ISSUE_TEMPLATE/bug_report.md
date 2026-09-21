---
name: Bug Report
about: Report a bug to help improve herdr-notify-router
title: "[BUG] "
labels: bug
assignees: ""
---

## Describe the Bug

A clear and concise description of what the bug is.

## Steps to Reproduce

1. Configure a rule and sink such as `...` (redact webhook URLs and tokens)
2. Trigger the event `...`
3. See error, or a notification that was sent or missed

## Expected Behaviour

What you expected to happen.

## Actual Behaviour

What actually happened. Include any error output, for example from
`herdr plugin log list --plugin pradyb.notify-router`.

## Environment

- **herdr version** (`herdr --version`):
- **herdr-notify-router version** (`version` in `herdr-plugin.toml`):
- **Python version** (`python3 --version`):
- **OS and architecture**:
- **Sink involved** (webhook, ntfy, desktop, ...):

## Additional Context

Any other context about the problem. Never paste real webhook URLs, tokens, or pane content.
