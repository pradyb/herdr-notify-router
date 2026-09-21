"""Checks for notify_router.py. Run: python3 test_notify_router.py (stdlib only)."""
import contextlib
import datetime
import http.server
import json
import os
import tempfile
import threading
import types
from unittest import mock

import notify_router as nr

SAMPLE = """
# comment
[settings]
quiet_hours = "22:00-07:00"   # trailing comment
dedupe_seconds = 300

[sinks.slack]
type = "webhook"
url_env = 'SLACK_URL'
ratio = 1.5
flag = true

[[rule]]
on = ["blocked", "done"]
after = 120

[[rule]]
on = [
  "idle",
]
to = ["slack"]
"""


def test_subset_parser_matches_real_parser():
    try:
        import tomllib
    except ImportError:
        return  # older Python: the subset parser is the only parser
    assert nr._parse_toml_subset(SAMPLE) == tomllib.loads(SAMPLE)


def _conf(personal=None, repo=None):
    """Temp config dir (+ optional repo with .git) -> (repo cwd, cleanup env set)."""
    root = tempfile.mkdtemp()
    cfg = os.path.join(root, "cfg")
    os.makedirs(cfg)
    if personal is not None:
        open(os.path.join(cfg, "notify.toml"), "w").write(personal)
    os.environ["NOTIFY_ROUTER_CONFIG_DIR"] = cfg
    os.environ["NOTIFY_ROUTER_STATE_DIR"] = os.path.join(root, "state")
    work = os.path.join(root, "repo", "src", "deep")
    os.makedirs(work)
    os.makedirs(os.path.join(root, "repo", ".git"))
    if repo is not None:
        os.makedirs(os.path.join(root, "repo", ".herdr"))
        open(os.path.join(root, "repo", ".herdr", "notify.toml"), "w").write(repo)
    return work


def test_repo_file_sets_rules_but_can_never_add_sinks():
    personal = '[sinks.mine]\ntype = "desktop"\n[[rule]]\non = ["idle"]\n'
    repo = '[sinks.evil]\ntype = "webhook"\nurl = "http://attacker"\n[settings]\nquiet_hours = "00:00-23:59"\n[[rule]]\non = ["blocked"]\nafter = 30\nto = ["mine"]\n'
    cfg = nr.load_config(_conf(personal, repo))
    assert list(cfg["sinks"]) == ["mine"] and cfg["settings"] == {}
    assert [r["on"] for r in cfg["rules"]] == [["blocked"]] and cfg["rules"][0]["after"] == 30  # repo rules win


def test_rule_fallbacks_and_validation():
    assert nr.load_config(_conf('[[rule]]\non = ["idle"]\n'))["rules"][0]["on"] == ["idle"]  # personal rules
    d = nr.load_config(_conf())["rules"][0]  # nothing configured -> built-in default
    assert d["on"] == ["blocked"] and d["after"] == 60 and d["skip_if_focused"] is True
    try:
        nr.load_config(_conf("[[rule]]\nafter = 5\n"))
        raise AssertionError("a rule without on= must be rejected")
    except ValueError:
        pass


def test_repo_config_is_found_from_a_subdirectory_but_not_beyond_the_git_root():
    work = _conf(repo="")
    assert nr.find_repo_config(work).endswith(os.path.join("repo", ".herdr", "notify.toml"))
    root = tempfile.mkdtemp()  # a .herdr above a nested repo must not leak into it
    os.makedirs(os.path.join(root, ".herdr"))
    open(os.path.join(root, ".herdr", "notify.toml"), "w").write("")
    os.makedirs(os.path.join(root, "inner", ".git"))
    os.makedirs(os.path.join(root, "inner", "a"))
    assert nr.find_repo_config(os.path.join(root, "inner", "a")) is None


def test_quiet_hours_including_wrap_past_midnight():
    at = lambda h, m: datetime.datetime(2026, 1, 1, h, m)
    assert nr.in_quiet_hours("22:00-07:00", at(23, 30)) and nr.in_quiet_hours("22:00-07:00", at(6, 59))
    assert not nr.in_quiet_hours("22:00-07:00", at(7, 0)) and not nr.in_quiet_hours("22:00-07:00", at(12, 0))
    assert nr.in_quiet_hours("09:00-17:00", at(9, 0)) and not nr.in_quiet_hours("09:00-17:00", at(17, 0))
    assert not nr.in_quiet_hours("", at(3, 0))
    try:
        nr.in_quiet_hours("nonsense", at(1, 0))
        raise AssertionError("bad quiet_hours must be rejected")
    except ValueError:
        pass


def test_webhook_payloads_do_not_let_pane_text_ping_people():
    text = nr.webhook_payload("slack", "t", "<!channel> <@U123> a&b", {})["text"]
    assert "<" not in text and ">" not in text and "a&amp;b" in text  # no mention or link syntax survives
    assert nr.webhook_payload("discord", "t", "@everyone", {})["allowed_mentions"] == {"parse": []}
    assert nr.webhook_payload("json", "t", "b", {"agent": "claude"}) == {"agent": "claude", "title": "t", "body": "b"}


# --- delivery logic, with herdr, the clock and the sinks faked out (all patches are scoped)

CFG = '[sinks.a]\ntype = "desktop"\n[sinks.b]\ntype = "ntfy"\ntopic = "t"\n'
NOON = datetime.datetime(2026, 1, 1, 12, 0)


class Fake:
    def __init__(self, config, focused=False):
        self.cwd = _conf(config)
        self.focused, self.status, self.fail = focused, "blocked", False
        self.sent, self.launched = [], []

    def pane(self, _pane):
        return {"agent": "claude", "agent_status": self.status, "focused": self.focused,
                "cwd": self.cwd, "workspace_id": "w1", "tab_id": "w1:t1"}

    def send(self, sink, title, body, info):
        if self.fail:
            raise OSError("boom")
        self.sent.append((sink["type"], title, body))

    def event(self, status):
        self.status = status
        os.environ["HERDR_PLUGIN_EVENT_JSON"] = json.dumps(
            {"event": "pane_agent_status_changed", "data": {"pane_id": "w1:p1", "agent_status": status, "agent": "claude"}})
        before = len(self.launched)
        nr.on_event()
        return self.launched[before:]


@contextlib.contextmanager
def fake(config, **kw):
    f = Fake(config, **kw)
    clock = types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda: NOON))
    with mock.patch.object(nr, "pane_info", f.pane), \
            mock.patch.object(nr, "label", lambda kind, ident: {"workspace": "api", "tab": "fix-bug"}[kind]), \
            mock.patch.object(nr, "send", f.send), mock.patch.object(nr, "datetime", clock), \
            mock.patch.object(nr.time, "sleep", lambda s: None), \
            mock.patch.object(nr.subprocess, "Popen", lambda argv, **kw: f.launched.append(argv)):
        yield f


RULE = '[[rule]]\non = ["blocked"]\n'


def test_immediate_rule_sends_once_to_every_sink_and_dedupes():
    with fake(RULE + CFG) as f:
        f.event("blocked")
        assert f.sent == [("desktop", "claude is blocked", "api / fix-bug"), ("ntfy", "claude is blocked", "api / fix-bug")]
        f.event("blocked")
        assert len(f.sent) == 2  # same pane/status/sink inside dedupe_seconds


def test_skip_if_focused_suppresses_unless_switched_off():
    with fake(RULE + CFG, focused=True) as f:
        f.event("blocked")
        assert f.sent == []
    with fake(RULE + "skip_if_focused = false\n" + CFG, focused=True) as f:
        f.event("blocked")
        assert len(f.sent) == 2


def test_quiet_hours_suppress_at_noon_only_when_the_window_covers_it():
    with fake('[settings]\nquiet_hours = "11:00-13:00"\n' + RULE + CFG) as f:
        f.event("blocked")
        assert f.sent == []
    with fake('[settings]\nquiet_hours = "13:00-14:00"\n' + RULE + CFG) as f:
        f.event("blocked")
        assert len(f.sent) == 2


def test_rule_targets_only_the_named_sinks_and_unknown_names_are_skipped():
    with fake(RULE + 'to = ["b", "nope"]\n' + CFG) as f:
        f.event("blocked")
        assert [x[0] for x in f.sent] == ["ntfy"]


def test_failed_send_is_retried_on_the_next_event():
    with fake(RULE + 'to = ["a"]\n' + CFG) as f:
        f.fail = True
        f.event("blocked")
        f.fail = False
        f.event("blocked")
        assert len(f.sent) == 1  # the failure did not burn the dedupe slot


def test_delayed_rule_starts_a_timer_and_fires_only_if_still_blocked():
    with fake(RULE + "after = 120\n" + CFG) as f:
        (argv,) = f.event("blocked")
        assert f.sent == []
        _, _, _, pane, status, token, after = argv
        nr.on_check(pane, status, token, int(after))
        assert len(f.sent) == 2 and "for 2 min" in f.sent[0][2]


def test_timer_is_cancelled_by_any_later_status_change():
    with fake(RULE + "after = 60\n" + CFG) as f:
        (argv,) = f.event("blocked")
        f.event("working")  # the agent resumed: this supersedes the pending alert
        nr.on_check(*argv[3:6], int(argv[6]))
        assert f.sent == []
        (argv,) = f.event("blocked")
        f.status = "working"  # changed without our hook seeing it: the live check catches it
        nr.on_check(*argv[3:6], int(argv[6]))
        assert f.sent == []


def test_a_flapping_agent_alerts_once_from_the_latest_timer_only():
    with fake(RULE + "after = 60\n" + CFG) as f:
        (first,) = f.event("blocked")
        f.event("working")
        (second,) = f.event("blocked")  # blocked again: the live status now matches the FIRST timer too
        nr.on_check(*first[3:6], int(first[6]))
        assert f.sent == []  # only the token tells the stale timer apart
        nr.on_check(*second[3:6], int(second[6]))
        assert len(f.sent) == 2


# --- real HTTP against a local server

class Catcher(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Catcher.seen.append((self.path, dict(self.headers), body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def _server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Catcher)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Catcher.seen.clear()
    return srv, "http://127.0.0.1:%d" % srv.server_port


def test_webhook_and_ntfy_really_post():
    srv, base = _server()
    info = {"agent": "claude", "status": "blocked", "pane_id": "w1:p1", "workspace": "api", "tab": "t"}
    nr.send({"type": "webhook", "url": base + "/hook", "format": "json"}, "claude is blocked", "api / t", info)
    nr.send({"type": "ntfy", "server": base, "topic": "my topic", "token": "tk_123"}, "Ünï is blocked", "api / t", info)
    srv.shutdown()
    (path1, h1, b1), (path2, h2, b2) = Catcher.seen
    assert path1 == "/hook" and json.loads(b1)["agent"] == "claude" and h1["Content-Type"] == "application/json"
    assert path2 == "/my%20topic" and b2 == b"api / t" and h2["Priority"] == "high" and h2["Authorization"] == "Bearer tk_123"
    assert h2["Title"] == "?n? is blocked"  # headers must be latin-1 safe


def test_only_http_urls_and_missing_urls_are_refused():
    for url in ("file:///etc/passwd", "ftp://x/y"):
        try:
            nr.send({"type": "webhook", "url": url}, "t", "b", {})
            raise AssertionError("must refuse " + url)
        except ValueError:
            pass
    try:
        nr.send({"type": "webhook", "url_env": "NOT_SET_ANYWHERE"}, "t", "b", {})
        raise AssertionError("must refuse a missing url")
    except ValueError:
        pass


def test_desktop_message_never_reaches_a_shell():
    calls = []
    evil = 'body"; do shell script "rm -rf ~"'
    with mock.patch.object(nr.subprocess, "run", lambda cmd, **kw: calls.append(cmd)), mock.patch.object(nr.sys, "platform", "darwin"):
        nr.send({"type": "desktop"}, 'a "title"', evil, {})
    assert calls[0][0] == "osascript" and calls[0][-2:] == [evil, 'a "title"']
    assert "rm -rf" not in calls[0][2]  # the script text itself is constant


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
