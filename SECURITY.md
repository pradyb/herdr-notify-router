# Security Policy

## Supported Versions

Only the latest release (and the latest commit on `main`) is actively supported with security fixes.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately using
[GitHub's private vulnerability reporting](https://github.com/pradyb/herdr-notify-router/security/advisories/new)
or by emailing **pradeep.devlabs@gmail.com**.

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept if possible)
- Your suggested fix or mitigation (optional)

You can expect an acknowledgement within **72 hours**.

## Scope

This plugin sends notifications to destinations you configure, so its sensitive data is the
webhook URLs and tokens in your config, and any pane content included in a message.

A `.herdr/notify.toml` committed to a repository is untrusted input: it may only choose rules
(which statuses matter, delays, which of *your* sinks to use). Sinks, URLs, tokens and quiet hours
are read only from your personal config.

In scope: any way a value from a pane, an agent, or a repo config can inject commands or
arguments, leak a webhook URL or token, add a sink or destination, or send data to a destination
that was not configured in your personal config.

Out of scope: what a sink you chose (Slack, ntfy, your own webhook, ...) does with a message,
and vulnerabilities in herdr itself (report those to the herdr project).
