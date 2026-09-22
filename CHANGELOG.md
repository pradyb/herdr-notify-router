# Changelog

All notable changes to herdr-notify-router will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1]

### Changed
- The test action's menu title now reads "Send a test notification (all sinks)", making clear it tests every configured sink at once rather than one at a time

## [0.3.0]

### Added
- **`include_pane_lines` rule field** (opt-in, off by default): appends the last N lines of a pane's real terminal output to the alert body. Truncated to a safe length and degrades silently (alert still sent, just without the extra text) if herdr can't read the pane. Documented as sending raw, potentially sensitive text to whatever sink the rule targets

## [0.2.2]

### Fixed
- **Discord webhooks were rejected with 403**: `_post()` sent no `User-Agent` header, and Discord's Cloudflare front blocks the default `Python-urllib/...` value as bot traffic. Every outbound request (`webhook` and `ntfy` sinks) now carries a descriptive `User-Agent`

## [0.2.1]

### Fixed
- **HTTPS sinks failed with python.org Python on macOS**: that Python ships with no CA certificates, so every HTTPS request (ntfy.sh, Slack, Discord) failed with `CERTIFICATE_VERIFY_FAILED`. When the default trust store is empty the plugin now loads a system CA bundle (`certifi` if installed, then the usual system paths). Certificate verification is never disabled

## [0.2.0]

### Added
- **Custom-icon desktop notifications on macOS**: the `desktop` sink accepts `notifier`, the path to a terminal-notifier binary (for example a copy built with your own icon, see the README). Titles and messages are passed as plain arguments, and values that terminal-notifier would read as syntax (a leading `-`, `[`, `(`, `{`, `<`, quote or backslash) are escaped so a workspace name like `-x` cannot break or alter the call

## [0.1.1]

### Fixed
- **Sessions no longer interfere with each other**: pending alerts and dedupe were keyed by pane id, which repeats across herdr sessions that share one plugin state directory, so activity in one session could cancel or suppress an alert in another. State is now scoped per session

## [0.1.0]

First release.

### Added
- Rules for `pane.agent_status_changed`: `on` (statuses), `after` (only alert if still in that status after N seconds), `skip_if_focused`, and `to` (which sinks)
- Sinks: webhook (`slack`, `discord` or `json` payloads), ntfy, and desktop notifications (macOS and `notify-send`)
- Quiet hours, and dedupe per pane, status and sink
- A committable `.herdr/notify.toml` for team rules; it can only set rules, never sinks or URLs
- "Send a test notification" action that posts to every configured sink
- Repository setup: license, contributing guide, security policy, issue and PR templates, code owners, and CI on Python 3.8 and the latest 3.x
