# Contributing

## Setup

```sh
git clone https://github.com/pradyb/herdr-notify-router
cd herdr-notify-router
herdr plugin link "$PWD"   # use your checkout as the installed plugin
```

## Before opening a PR

```sh
python3 -m compileall -q .
python3 test_notify_router.py
```

CI runs the same checks on Python 3.8 and the latest 3.x for every push and PR.

## Guidelines

- Keep the plugin dependency-free (Python standard library only, 3.8+).
- Add a check to `test_notify_router.py` for any new rule or sink behaviour.
- Update the README if you change user-facing behaviour.
- Bump `version` in `herdr-plugin.toml` and add an entry to `CHANGELOG.md` for any change users would notice.
- Never commit real webhook URLs, tokens, or pane content, including in tests and fixtures.

## Questions

For usage questions or half-formed ideas, use
[Discussions](https://github.com/pradyb/herdr-notify-router/discussions) rather than
the issue tracker. Issues are for reproducible bugs and concrete feature requests.
