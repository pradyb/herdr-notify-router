# herdr notify-router

Rules for your [herdr](https://herdr.dev) agent notifications: decide **when** an
alert is worth sending and **where** it goes, instead of forwarding every event to one channel.

- Alert when an agent is `blocked`, but only if it **stays** blocked for N seconds
- Skip the alert when you are already looking at that pane
- Quiet hours, and no repeats of the same alert
- Send to a webhook (Slack, Discord, or your own), [ntfy](https://ntfy.sh), or a desktop notification
- Commit a `.herdr/notify.toml` so a team shares one policy, while each person keeps their own channels

This is an unofficial community plugin. It is not affiliated with or endorsed
by herdr.

## Requirements

- herdr 0.9.1 or newer (the only version tested so far)
- `python3` on your PATH. It only uses the standard library, so any Python 3.8+ works.
- Linux or macOS

## Install

```sh
herdr plugin install pradyb/herdr-notify-router
```

Or from a local clone, for development: `herdr plugin link "$PWD"`.

## Quick start

Create `notify.toml` in the plugin's config directory (`herdr plugin config-dir pradyb.notify-router`):

```toml
[sinks.phone]
type = "ntfy"
topic = "my-herdr-alerts"

[sinks.mac]
type = "desktop"
```

Then check that each sink works:

```sh
herdr plugin action invoke test --plugin pradyb.notify-router
herdr plugin log list --plugin pradyb.notify-router   # shows "ok: phone" / "FAILED: ..."
```

With no rules at all, you get one built-in rule: alert on `blocked` after 60 seconds, to every sink,
unless you are looking at that pane.

## Configuration

### Sinks (personal config only)

Verified against real services: `ntfy` (published to ntfy.sh and read back), macOS `desktop`, and the
`webhook` sink's `slack` and `discord` formats (each delivered to a real webhook). `notify-send` on Linux
is untested — see [Limits](#limits).

| Type | Fields |
|---|---|
| `webhook` | `url` or `url_env`; `format` = `slack` (default), `discord` or `json` |
| `ntfy` | `topic`; `server` (default `https://ntfy.sh`); `token` or `token_env` for a protected topic. Non-ASCII characters in the title (the agent name) are shown as `?`; the message is unaffected. |
| `desktop` | `notifier` (optional, macOS): path to a terminal-notifier binary, for a [custom icon](#custom-icon-on-macos). Otherwise `osascript` on macOS and `notify-send` on Linux. |

```toml
[sinks.team-chat]
type = "webhook"
format = "slack"
url_env = "SLACK_WEBHOOK_URL"
```

> **`url_env` reads herdr's environment, not your shell's.** The variable must be set in the
> process that started the herdr server. If it is missing you get an error in the plugin log.
> Putting the URL in `url` works everywhere; keep that file private (`chmod 600`).

The `slack` payload is `{"text": ...}` with `&`, `<` and `>` escaped, so a branch or workspace name
cannot trigger a mention. The `discord` payload disables all mentions.

### Custom icon on macOS

`osascript` notifications always show the Script Editor icon: macOS takes a notification's icon from
the app that sends it, and offers no way to override it. To get your own icon, build a copy of
[terminal-notifier](https://github.com/julienXX/terminal-notifier) that carries it (needs the Xcode
command line tools):

```sh
git clone https://github.com/julienXX/terminal-notifier && cd terminal-notifier
make icon ICON=~/Pictures/my-icon.png APP_NAME=herdr-notify-router
cp -R build/herdr-notify-router.app ~/Applications/
```

Run it once **from a normal terminal** and click *Allow*, so macOS asks you for permission
(it appears in System Settings → Notifications under the app name):

```sh
~/Applications/herdr-notify-router.app/Contents/MacOS/terminal-notifier -title test -message hello
```

Then point the sink at it:

```toml
[sinks.mac]
type = "desktop"
notifier = "~/Applications/herdr-notify-router.app/Contents/MacOS/terminal-notifier"
```

The plugin does not ship an icon. herdr's logo is herdr's brand asset, so if you use it, keep it on
your own machine. terminal-notifier's own `-appIcon` and `-sender` options no longer work on modern
macOS, so a custom app copy is the only route to a different icon.

### Rules

```toml
[[rule]]
on = ["blocked"]          # agent statuses that trigger it
after = 120               # seconds the agent must still be in that status (default 0 = at once)
skip_if_focused = true    # don't alert for the pane you are looking at (default true)
to = ["phone", "mac"]     # which sinks (default: all of them)
```

Statuses come from herdr: `idle`, `working`, `blocked`, `done` and `unknown`. Only
`idle`, `working` and `blocked` have been exercised in tests so far.

An alert with `after` is cancelled if the agent changes status in the meantime, even if it
returns to the same status: only the latest episode alerts.

`skip_if_focused` uses herdr's one focused pane. herdr always has one, even when no client is
attached, so it cannot tell whether anyone is actually watching.

### Settings (personal config only)

```toml
[settings]
quiet_hours = "22:00-07:00"   # local time; may wrap past midnight; alerts inside it are dropped
dedupe_seconds = 300          # don't repeat the same pane + status + sink within this time (default 300)
```

## Team policy: `.herdr/notify.toml`

Commit a `.herdr/notify.toml` at the root of a repository to share **rules**:

```toml
# .herdr/notify.toml
[[rule]]
on = ["blocked"]
after = 180
to = ["team-chat"]
```

- The nearest file at or above the pane's working directory is used, without leaving the git repo.
- If it has rules, they **replace** your personal rules for panes in that repo.
- It can only set rules. Any `[sinks]` or `[settings]` in it are ignored, so a repo can never add a
  destination or a webhook URL. Rules refer to sinks by name, so every teammate defines a sink with that
  name (for example `team-chat`) in their own config, each pointing where they want.

## Limits

- **No Microsoft Teams.** Teams webhooks expect an Adaptive Card, which is not implemented yet.
- **`notify-send` on Linux has not been verified against a real Linux desktop** (everything else has —
  see the note under Sinks below). Run the `test` action to check it on your machine.
- **Alerts don't contain pane content**, only the agent, workspace and tab names.
- A pending `after` alert is a sleeping background process. It is lost if the machine restarts.

## Troubleshooting

- **`certificate verify failed`:** Python from python.org on macOS has no CA certificates of its own. The
  plugin falls back to the system bundle (`/etc/ssl/cert.pem`, or `certifi` if installed). If you still see
  this, run the "Install Certificates.command" that comes with that Python.
- **Nothing arrives:** `herdr plugin log list --plugin pradyb.notify-router`. Hook failures and
  sink errors (class and HTTP status only, never the URL) appear there.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
