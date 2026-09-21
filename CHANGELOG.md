# Changelog

All notable changes to herdr-notify-router will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

First release.

### Added
- Rules for `pane.agent_status_changed`: `on` (statuses), `after` (only alert if still in that status after N seconds), `skip_if_focused`, and `to` (which sinks)
- Sinks: webhook (`slack`, `discord` or `json` payloads), ntfy, and desktop notifications (macOS and `notify-send`)
- Quiet hours, and dedupe per pane, status and sink
- A committable `.herdr/notify.toml` for team rules; it can only set rules, never sinks or URLs
- "Send a test notification" action that posts to every configured sink
- Repository setup: license, contributing guide, security policy, issue and PR templates, code owners, and CI on Python 3.8 and the latest 3.x
