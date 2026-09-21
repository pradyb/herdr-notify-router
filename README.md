# herdr notify-router

Rules for your [herdr](https://herdr.dev) agent notifications: decide **when** an
alert is worth sending and **where** it goes, instead of forwarding every event to one channel.

> **Status: in development.** Nothing is implemented yet. The list below is the plan.

This is an unofficial community plugin. It is not affiliated with or endorsed
by herdr.

## Planned

- Notify when an agent is `blocked` or `done`, but only if it is still blocked after N minutes
- Skip the alert when you are already looking at that pane
- Quiet hours, dedupe, and escalation to a second channel if unanswered
- Sinks: generic webhook (Slack, Teams, Discord), ntfy, and macOS desktop notifications
- An optional end-of-day digest
- A `.herdr/notify.toml` you can commit so a team shares one policy, while each person keeps their own channels and quiet hours locally

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
