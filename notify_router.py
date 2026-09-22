#!/usr/bin/env python3
"""herdr notify-router: decide when an agent alert is worth sending, and where it goes.

Runs as a herdr event hook on pane.agent_status_changed. Rules and sinks live in
notify.toml (see README.md). Standard library only (Python 3.8+).
"""
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
VERSION = "0.3.0"  # keep in sync with herdr-plugin.toml's version (only used in the User-Agent string)
# Used when no notify.toml has any rules: an agent stuck blocked for a minute.
DEFAULT_RULES = [{"on": ["blocked"], "after": 60}]
DEVNULL = subprocess.DEVNULL

# ----------------------------------------------------------------- config


def _skip(s):
    """Drop leading whitespace and # comments (inside multi-line arrays)."""
    s = s.lstrip()
    while s.startswith("#"):
        s = s.split("\n", 1)[1].lstrip() if "\n" in s else ""
    return s


def _value(s):
    """Parse one TOML scalar or flat array at the start of s -> (value, rest)."""
    s = s.lstrip()
    if s[0] == '"':
        end = 1
        while s[end] != '"':
            end += 2 if s[end] == "\\" else 1
        return json.loads(s[: end + 1]), s[end + 1 :]
    if s[0] == "'":
        end = s.index("'", 1)
        return s[1:end], s[end + 1 :]
    if s[0] == "[":
        items, rest = [], _skip(s[1:])
        while not rest.startswith("]"):
            v, rest = _value(rest)
            items.append(v)
            rest = _skip(rest)
            if rest.startswith(","):
                rest = _skip(rest[1:])
        return items, rest[1:]
    tok = re.match(r"[^\s,\]#]+", s).group(0)
    if tok in ("true", "false"):
        return tok == "true", s[len(tok) :]
    try:
        return int(tok), s[len(tok) :]
    except ValueError:
        return float(tok), s[len(tok) :]


def _table(data, path, array):
    node = data
    for i, key in enumerate(path):
        if array and i == len(path) - 1:
            node = node.setdefault(key, [])
            node.append({})
            return node[-1]
        node = node.setdefault(key, {})
        if isinstance(node, list):
            node = node[-1]
    return node


def _parse_toml_subset(text):
    """Fallback for Pythons without tomllib/tomli.

    Supports what notify.toml needs: [a.b] tables, [[a]] arrays of tables, and
    key = string | number | bool | flat array, with # comments.
    """
    data = {}
    cur = data
    lines = enumerate(text.splitlines(), 1)
    for lineno, raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            m = re.fullmatch(r"\[\[\s*([\w.\-]+)\s*\]\]\s*(#.*)?", line)
            if m:
                cur = _table(data, m.group(1).split("."), True)
                continue
            m = re.fullmatch(r"\[\s*([\w.\-]+)\s*\]\s*(#.*)?", line)
            if m:
                cur = _table(data, m.group(1).split("."), False)
                continue
            m = re.fullmatch(r"([\w\-]+)\s*=\s*(.+)", line)
            rest = m.group(2)
            while rest.lstrip().startswith("[") and rest.count("[") > rest.count("]"):
                rest += "\n" + next(lines)[1]  # array continues on the next line
            val, rest = _value(rest)
            if rest.strip() and not rest.strip().startswith("#"):
                raise ValueError("trailing text")
            cur[m.group(1)] = val
        except (AttributeError, ValueError, IndexError, KeyError, StopIteration):
            raise ValueError("notify.toml line %d: cannot parse: %s" % (lineno, raw)) from None
    return data


def load_toml(path):
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    try:
        import tomllib  # 3.11+

        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli

        return tomli.loads(text)
    except ImportError:
        return _parse_toml_subset(text)


def _dir(override, herdr_var):
    return os.environ.get(override) or os.environ.get(herdr_var, "")


def config_dir():
    return _dir("NOTIFY_ROUTER_CONFIG_DIR", "HERDR_PLUGIN_CONFIG_DIR")


def state_dir():
    return _dir("NOTIFY_ROUTER_STATE_DIR", "HERDR_PLUGIN_STATE_DIR")


def find_repo_config(cwd):
    """Nearest .herdr/notify.toml at or above cwd, without leaving the git repo."""
    d = os.path.abspath(cwd or ".")
    for _ in range(40):
        p = os.path.join(d, ".herdr", "notify.toml")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if os.path.exists(os.path.join(d, ".git")) or parent == d:
            return None
        d = parent
    return None


def _rule(r):
    on = r.get("on")
    if not isinstance(on, list) or not on:
        raise ValueError('every [[rule]] needs on = ["blocked", ...]')
    return {
        "on": [str(x) for x in on],
        "after": max(0, int(r.get("after", 0))),
        "skip_if_focused": bool(r.get("skip_if_focused", True)),
        "to": r.get("to"),
        "include_pane_lines": max(0, int(r.get("include_pane_lines", 0))),
    }


def load_config(cwd):
    """Sinks and settings come only from the personal file; a repo file may only set rules."""
    personal_path = os.path.join(config_dir(), "notify.toml")
    personal = load_toml(personal_path) if os.path.isfile(personal_path) else {}
    repo_path = find_repo_config(cwd)
    repo = load_toml(repo_path) if repo_path else {}
    rules = repo.get("rule") or personal.get("rule") or DEFAULT_RULES
    return {
        "settings": personal.get("settings", {}),
        "sinks": personal.get("sinks", {}),
        "rules": [_rule(r) for r in rules],
    }


def in_quiet_hours(spec, now):
    if not spec:
        return False
    m = re.fullmatch(r"(\d\d):(\d\d)-(\d\d):(\d\d)", str(spec).strip())
    if not m:
        raise ValueError("quiet_hours must look like 22:00-07:00")
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    t = now.hour * 60 + now.minute
    return a <= t < b if a <= b else (t >= a or t < b)


# ----------------------------------------------------------------- state


@contextlib.contextmanager
def state():
    """Locked, persistent {episodes, sent}. Several hooks can run at once."""
    d = state_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "state.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = os.path.join(d, "state.json")
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data.setdefault("episodes", {})
        data.setdefault("sent", {})
        yield data
        cutoff = time.time() - 86400
        data["episodes"] = {k: v for k, v in data["episodes"].items() if v["ts"] > cutoff}
        data["sent"] = {k: v for k, v in data["sent"].items() if v > cutoff}
        with open(path + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)


# ----------------------------------------------------------------- herdr


def herdr_json(*args):
    p = subprocess.run([HERDR, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip() or "herdr %s failed" % " ".join(args))
    return json.loads(p.stdout)["result"]


def pane_info(pane):
    return herdr_json("pane", "get", pane)["pane"]


MAX_PANE_CHARS = 1200  # keeps title + body well under Discord's 2000-char content limit


def pane_read(pane, lines):
    """Last N lines of real terminal output, or None if herdr can't read it right now.

    Unlike every other herdr subcommand, `pane read` prints plain text straight to
    stdout, not the usual {"result": ...} JSON envelope -- so this bypasses herdr_json().
    """
    try:
        p = subprocess.run([HERDR, "pane", "read", pane, "--source", "recent", "--lines", str(lines), "--format", "text"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip() or "pane read failed")
        text = p.stdout
    except Exception as e:  # noqa: BLE001  (pane closed, herdr error, ...): degrade, don't fail the alert
        log("pane read failed: %s" % _failure(e))
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_PANE_CHARS:
        text = "…" + text[-MAX_PANE_CHARS:]
    return text


def label(kind, ident):
    return herdr_json(kind, "get", ident)[kind]["label"]


# ----------------------------------------------------------------- sinks


def _flagsafe(s):
    """terminal-notifier parses values as plist text (a leading - [ ( { < or quote is syntax)
    and strips one leading backslash, so a backslash makes such a value literal."""
    return "\\" + s if s.startswith(("-", "[", "(", "{", "<", '"', "'", "\\")) else s


def _ascii(s):
    return s.encode("ascii", "replace").decode()


def _ssl_context():
    """python.org's macOS Python ships with no CA certificates; fall back to a system bundle.

    Verification is never turned off: with no bundle found the default context (and its error) is used.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"]:
        return ctx
    bundles = []
    try:
        import certifi

        bundles.append(certifi.where())
    except ImportError:
        pass
    bundles += ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"]
    for path in bundles:
        if os.path.isfile(path):
            return ssl.create_default_context(cafile=path)
    return ctx


USER_AGENT = "herdr-notify-router (https://github.com/pradyb/herdr-notify-router, %s)" % VERSION


def _post(url, data, headers):
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError("url must be http(s)")
    # Some targets (Discord's Cloudflare front, at least) reject urllib's default
    # User-Agent as bot traffic (HTTP 403 before the request reaches the app).
    req = urllib.request.Request(url, data=data, headers=dict(headers, **{"User-Agent": USER_AGENT}), method="POST")
    urllib.request.urlopen(req, timeout=10, context=_ssl_context()).read()


def webhook_payload(fmt, title, body, info):
    text = "%s — %s" % (title, body)
    if fmt == "discord":
        return {"content": text, "allowed_mentions": {"parse": []}}  # no @everyone from a branch name
    if fmt == "json":
        return dict(info, title=title, body=body)
    if fmt == "slack":  # the {"text": ...} shape used by Slack incoming webhooks
        return {"text": text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}
    raise ValueError("format must be slack, discord or json")


def send(sink, title, body, info):
    kind = sink.get("type")
    if kind == "webhook":
        url = sink.get("url") or os.environ.get(sink.get("url_env", ""), "")
        if not url:
            raise ValueError("webhook needs url or url_env (and the variable must be set in herdr's environment)")
        payload = webhook_payload(sink.get("format", "slack"), title, body, info)
        _post(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    elif kind == "ntfy":
        url = "%s/%s" % (sink.get("server", "https://ntfy.sh").rstrip("/"), urllib.parse.quote(sink["topic"], safe=""))
        headers = {"Title": _ascii(title), "Priority": "high" if info["status"] == "blocked" else "default"}
        token = sink.get("token") or os.environ.get(sink.get("token_env", ""), "")
        if token:
            headers["Authorization"] = "Bearer " + token
        _post(url, body.encode("utf-8"), headers)
    elif kind == "desktop":
        if sink.get("notifier"):  # a terminal-notifier binary, e.g. a copy built with your own icon
            cmd = [os.path.expanduser(sink["notifier"]), "-title", _flagsafe(title), "-message", _flagsafe(body)]
        elif sys.platform == "darwin":
            script = "on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv)\nend run"
            cmd = ["osascript", "-e", script, body, title]  # argv, never interpolated into the script
        elif shutil.which("notify-send"):
            cmd = ["notify-send", "--", title, body]
        else:
            raise RuntimeError("no desktop notifier (needs osascript or notify-send)")
        subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL, check=True, timeout=10)
    else:
        raise ValueError("sink type must be webhook, ntfy or desktop")


def log(msg):
    print("notify-router: " + msg, file=sys.stderr)


def _failure(e):
    code = getattr(e, "code", "")  # class and HTTP code only: messages can carry URLs
    return type(e).__name__ + (" %s" % code if code else "")


# ----------------------------------------------------------------- routing


def pane_key(pane):
    """Pane ids repeat across sessions (each has its own w1:p1) but all share one state dir."""
    return "%s\x1f%s" % (os.environ.get("HERDR_SOCKET_PATH", ""), pane)


def message(info, waited, pane_text=None):
    title = "%s is %s" % (info["agent"] or "agent", info["status"])
    body = "%s / %s" % (info["workspace"], info["tab"])
    if waited:
        body += " · for %s" % ("%d min" % (waited // 60) if waited >= 60 else "%d s" % waited)
    if pane_text:
        body += "\n\n" + pane_text
    return title, body


def deliver(cfg, rule, pane, status, waited):
    if in_quiet_hours(cfg["settings"].get("quiet_hours"), datetime.datetime.now()):
        return
    raw = pane_info(pane)
    if rule["skip_if_focused"] and raw.get("focused"):
        return
    info = {
        "agent": raw.get("agent"),
        "status": status,
        "pane_id": pane,
        "workspace": label("workspace", raw["workspace_id"]),
        "tab": label("tab", raw["tab_id"]),
    }
    pane_text = pane_read(pane, rule["include_pane_lines"]) if rule["include_pane_lines"] else None
    title, body = message(info, waited, pane_text)
    dedupe = int(cfg["settings"].get("dedupe_seconds", 300))
    for name in rule["to"] or list(cfg["sinks"]):
        sink = cfg["sinks"].get(name)
        if sink is None:
            log("unknown sink %r in a rule" % name)
            continue
        key = "%s\x1f%s\x1f%s" % (pane_key(pane), status, name)
        with state() as st:
            if time.time() - st["sent"].get(key, 0) < dedupe:
                continue
            st["sent"][key] = time.time()  # claim first so two hooks cannot both send
        try:
            send(sink, title, body, info)
        except Exception as e:  # noqa: BLE001
            log("sink %s failed: %s" % (name, _failure(e)))
            with state() as st:
                st["sent"].pop(key, None)  # let the next event retry


def on_event():
    data = json.loads(os.environ["HERDR_PLUGIN_EVENT_JSON"])["data"]
    pane, status = data["pane_id"], data["agent_status"]
    token = "%s.%s" % (time.time(), os.getpid())
    with state() as st:  # any later status change for this pane supersedes pending timers
        st["episodes"][pane_key(pane)] = {"status": status, "token": token, "ts": time.time()}
    cfg = load_config(pane_info(pane).get("cwd"))
    delays = set()
    for rule in cfg["rules"]:
        if status not in rule["on"]:
            continue
        if rule["after"]:
            delays.add(rule["after"])
        else:
            deliver(cfg, rule, pane, status, 0)
    for after in delays:
        # ponytail: one sleeping process per pending alert; a scheduler daemon if that ever matters
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--check", pane, status, token, str(after)],
            stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True,
        )


def on_check(pane, status, token, after):
    """Timer body: alert only if the pane is still in the same status episode."""
    time.sleep(after)
    with state() as st:
        episode = st["episodes"].get(pane_key(pane))
    if not episode or episode["token"] != token:
        return
    raw = pane_info(pane)
    if raw.get("agent_status") != status:
        return
    cfg = load_config(raw.get("cwd"))
    for rule in cfg["rules"]:
        if status in rule["on"] and rule["after"] == after:
            deliver(cfg, rule, pane, status, after)


def on_test():
    cfg = load_config(os.getcwd())
    if not cfg["sinks"]:
        raise ValueError("no sinks configured in %s" % os.path.join(config_dir(), "notify.toml"))
    info = {"agent": "notify-router", "status": "test", "pane_id": "", "workspace": "-", "tab": "-"}
    failed = 0
    for name, sink in cfg["sinks"].items():
        try:
            send(sink, "notify-router test", "If you can read this, sink %s works." % name, info)
            print("ok: " + name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAILED: %s (%s)" % (name, _failure(e)))
    return 1 if failed else 0


def main(argv):
    try:
        if argv[1:2] == ["--check"]:
            on_check(argv[2], argv[3], argv[4], int(argv[5]))
        elif argv[1:2] == ["--test"]:
            return on_test()
        else:
            on_event()
    except Exception as e:  # noqa: BLE001
        log("%s: %s" % (type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
