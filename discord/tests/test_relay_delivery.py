"""Delivery: secrets, retries, rate limits, time-outs, re-runs and what is shown in the log.

Every request goes to a receiver on 127.0.0.1 and the sleeping is recorded, not done."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import (
    FIXTURES,
    api_env,
    HOOK_PATH,
    RELAY_FILE,
    ROOT,
    TOKENS,
    receiver,
    relay,
    run_relay,
    skip_loudly,
)  # noqa: E402,F401

ISSUE = json.loads((FIXTURES / "events" / "issue_opened_labels.json").read_text())
PUSH_MANY = json.loads((FIXTURES / "events" / "push_many.json").read_text())
RELEASE = json.loads((FIXTURES / "events" / "release_stable.json").read_text())
FEED = TOKENS["DISCORD_WEBHOOK_FEED"]


def send_issue(tmp_path, receiver, **kwargs):
    return run_relay(tmp_path, ISSUE["event_name"], ISSUE["payload"], receiver, **kwargs)


def answer(status, body=b"{}", **headers):
    return status, headers, body


# ---------------------------------------------------------------- the request itself


def test_a_post_is_a_json_request_with_wait_and_no_credentials(receiver, tmp_path):
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and len(receiver.requests) == 1
    request = receiver.requests[0]
    assert request["query"] == "wait=true"
    assert request["headers"]["content-type"] == "application/json"
    assert request["headers"]["user-agent"].startswith("github-relay/")
    assert "authorization" not in request["headers"]
    assert request["raw"].isascii()


def test_each_kind_goes_to_its_own_webhook(receiver, tmp_path):
    run_relay(tmp_path, RELEASE["event_name"], RELEASE["payload"], receiver)
    announcement = json.loads((FIXTURES / "events" / "discussion_announcement.json").read_text())
    run_relay(tmp_path, announcement["event_name"], announcement["payload"], receiver)
    send_issue(tmp_path, receiver)
    assert [post["secret"] for post in receiver.posts()] == [
        "DISCORD_WEBHOOK_RELEASES",
        "DISCORD_WEBHOOK_ANNOUNCEMENTS",
        "DISCORD_WEBHOOK_FEED",
    ]


def test_every_request_has_a_ten_second_timeout(receiver, tmp_path, monkeypatch):
    seen = []

    class Spy:
        def open(self, request, timeout=None):
            seen.append(timeout)
            raise OSError("stop")

    monkeypatch.setattr(relay, "OPENER", Spy())
    send_issue(tmp_path, receiver)
    assert seen and set(seen) == {10}


# ---------------------------------------------------------------- missing and wrong secrets


def test_a_missing_secret_is_a_notice_and_a_clean_exit(receiver, tmp_path):
    run = send_issue(tmp_path, receiver, secrets={})
    assert run.code == 0 and receiver.requests == []
    assert "::notice title=Discord relay::The secret DISCORD_WEBHOOK_FEED is not set" in run.out
    assert "DISCORD_WEBHOOK_FEED is not set" in run.summary


def test_an_empty_secret_counts_as_missing(receiver, tmp_path):
    run = send_issue(tmp_path, receiver, secrets={"DISCORD_WEBHOOK_FEED": "   "})
    assert run.code == 0 and receiver.requests == []


def test_one_missing_secret_does_not_stop_the_others(receiver, tmp_path):
    run = run_relay(
        tmp_path,
        PUSH_MANY["event_name"],
        PUSH_MANY["payload"],
        receiver,
        secrets=receiver.env(["DISCORD_WEBHOOK_RELEASES"]),
    )
    assert run.code == 0 and receiver.requests == []
    release = run_relay(
        tmp_path,
        RELEASE["event_name"],
        RELEASE["payload"],
        receiver,
        secrets=receiver.env(["DISCORD_WEBHOOK_RELEASES"]),
    )
    assert release.code == 0 and len(receiver.posts()) == 1


def test_the_script_run_as_a_program_exits_zero_with_no_secrets(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(ISSUE["payload"]))
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_EVENT_NAME": "issues", "GITHUB_EVENT_PATH": str(event)}
    result = subprocess.run(
        [sys.executable, "-I", str(RELAY_FILE), "--layout", str(FIXTURES / "layout.toml")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "::notice title=Discord relay::" in result.stdout


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test" + HOOK_PATH + "1/abc",
        "http://discord.com" + HOOK_PATH + "1/abc",
        "https://discord.com.evil.test" + HOOK_PATH + "1/abc",
        "https://user:pw@discord.com" + HOOK_PATH + "1/abc",
        "file:///etc/passwd",
        "not a url",
        "https://discord.com/other/path",
    ],
)
def test_a_value_that_is_not_a_discord_webhook_address_is_refused_and_never_printed(receiver, tmp_path, value):
    run = send_issue(tmp_path, receiver, secrets={"DISCORD_WEBHOOK_FEED": value})
    assert run.code == 1 and receiver.requests == []
    assert "is not a Discord webhook address" in run.out
    assert value not in run.out and value not in run.summary


def test_loopback_is_refused_unless_the_test_switch_is_on(receiver, tmp_path):
    run = send_issue(tmp_path, receiver, extra_env={"RELAY_ALLOW_LOOPBACK": "0"})
    assert run.code == 1 and receiver.requests == []


# ---------------------------------------------------------------- retries


def test_server_errors_are_retried_after_2_and_8_seconds(receiver, tmp_path):
    receiver.script[FEED] = [answer(502), answer(500)]
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and len(receiver.requests) == 3
    assert run.sleeps == [2, 8]


def test_a_dropped_connection_is_retried(receiver, tmp_path):
    receiver.script[FEED] = [answer(0)]
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and len(receiver.requests) == 2 and run.sleeps == [2]


def test_three_retries_then_a_visible_failure_that_names_no_address(receiver, tmp_path):
    receiver.script[FEED] = [answer(503)] * 5
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 4
    assert run.sleeps == [2, 8, 30]
    assert "::error title=Discord relay::issue 412 to DISCORD_WEBHOOK_FEED failed: 503." in run.out
    assert "failed: 503" in run.summary
    for secret_text in (receiver.address("DISCORD_WEBHOOK_FEED"), FEED, str(receiver.port)):
        assert secret_text not in run.out and secret_text not in run.summary


def test_a_failure_does_not_stop_the_other_posts(receiver, tmp_path):
    receiver.script[FEED] = [answer(400, b'{"code": 50035}'), answer(200)]
    run = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver)
    assert run.code == 1
    assert len(receiver.requests) == 6  # the first failed once and the other five still went
    assert run.summary.count("| failed: 400") == 1 and run.summary.count("posted to DISCORD_WEBHOOK_FEED") == 5


def test_a_bad_request_stops_at_once(receiver, tmp_path):
    receiver.script[FEED] = [answer(400, b'{"message": "Invalid Form Body"}')]
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 1 and run.sleeps == []
    assert "Invalid Form Body" not in run.out


def test_a_deleted_webhook_is_not_tried_again(receiver, tmp_path):
    receiver.script[FEED] = [answer(404)]
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 1 and run.sleeps == []
    assert "404 and the webhook no longer exists" in run.out


def test_a_redirect_is_never_followed(receiver, tmp_path):
    receiver.script[FEED] = [answer(307, b"", Location=receiver.base + "/elsewhere")]
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 1


# ---------------------------------------------------------------- rate limits


def test_a_429_waits_for_retry_after_and_tries_again(receiver, tmp_path):
    receiver.script[FEED] = [
        answer(429, b'{"message": "rate limited", "retry_after": 1.5, "global": false}', **{"Retry-After": "2"})
    ]
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and len(receiver.requests) == 2
    assert run.sleeps == [1.5]


def test_a_429_without_a_body_uses_the_header(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b"", **{"Retry-After": "3"})]
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and run.sleeps == [3.0]


def test_a_wait_of_more_than_a_minute_is_not_taken(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b'{"retry_after": 61}')]
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 1 and run.sleeps == []
    assert "429" in run.out


def test_a_wait_of_exactly_a_minute_is_taken(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b'{"retry_after": 60}')]
    run = send_issue(tmp_path, receiver)
    assert run.code == 0 and run.sleeps == [60]


def test_rate_limits_are_given_up_on_after_five_waits(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b'{"retry_after": 1}')] * 10
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and len(receiver.requests) == 6 and run.sleeps == [1] * 5


def test_the_whole_run_has_a_time_budget(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b'{"retry_after": 60}')] * 10
    run = send_issue(tmp_path, receiver)
    assert run.code == 1
    assert run.sleeps == [60, 60]  # a third wait would pass 150 seconds
    assert "out of time" in run.out


def test_the_budget_also_stops_server_error_retries(receiver, tmp_path):
    receiver.script[FEED] = [answer(429, b'{"retry_after": 60}')] * 2 + [answer(500)] * 10
    run = send_issue(tmp_path, receiver)
    assert run.code == 1 and "out of time" in run.out
    assert run.sleeps == [60, 60, 2, 8]  # the next wait of 30 seconds would pass 150


def test_an_empty_rate_limit_bucket_is_waited_out_after_a_post(receiver, tmp_path):
    receiver.script[FEED] = [answer(200, b"{}", **{"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "1.2"})]
    run = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver)
    assert run.code == 0 and run.sleeps == [1.2]


# ---------------------------------------------------------------- re-runs


def attempt_env(receiver, attempt=2, attempt_run_id="77"):
    if RUNS_PATH not in receiver.api:  # the hourly cap reads the recent runs whenever a feed post is sent
        history(receiver, [], current=int(attempt_run_id))
    return {
        "GITHUB_RUN_ATTEMPT": str(attempt),
        "GITHUB_RUN_ID": "77",
        "GITHUB_REPOSITORY": "example-org/example",
        "GITHUB_JOB": "relay",
        "GITHUB_API_URL": receiver.base,
        "GITHUB_TOKEN": "token-for-the-api",
    }


JOBS = "/repos/example-org/example/actions/runs/77/attempts/1/jobs"


def jobs_answer(conclusion, job_id=55):
    return 200, {}, json.dumps({"jobs": [{"id": job_id, "name": "relay", "conclusion": conclusion}]}).encode()


def test_the_first_attempt_never_asks_github(receiver, tmp_path):
    run = send_issue(tmp_path, receiver, extra_env=attempt_env(receiver, 1))
    assert run.code == 0 and not [r for r in receiver.requests if "/attempts/" in r.get("path", "")]


def test_a_second_attempt_after_a_success_posts_nothing(receiver, tmp_path):
    receiver.api[JOBS] = jobs_answer("success")
    run = send_issue(tmp_path, receiver, extra_env=attempt_env(receiver))
    assert run.code == 0
    assert [r for r in receiver.requests if r.get("method") != "GET"] == []
    assert "already posted" in run.out.lower() and "already posted" in run.summary.lower()
    get = receiver.requests[0]
    assert get["path"] == JOBS and get["headers"]["authorization"] == "Bearer token-for-the-api"


def test_a_second_attempt_after_a_failure_posts_only_what_the_log_does_not_show(receiver, tmp_path):
    first = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver)
    markers = [line for line in first.out.splitlines() if "relay-posted" in line]
    assert len(markers) == 6
    receiver.requests.clear()
    log = "\n".join(f"2026-12-01T10:00:0{i}.000Z {line}" for i, line in enumerate(markers[:3])).encode()
    receiver.api[JOBS] = jobs_answer("failure")
    receiver.api["/repos/example-org/example/actions/jobs/55/logs"] = (200, {}, log)
    run = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver, extra_env=attempt_env(receiver))
    assert run.code == 0
    posts = receiver.posts()
    assert len(posts) == 3
    assert "feature number 0" not in json.dumps(posts) and "feature number 3" in json.dumps(posts)
    assert run.out.count("already posted") == 3


def test_the_log_is_fetched_from_its_redirect_without_the_token(receiver, tmp_path):
    first = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver)
    marker = [line for line in first.out.splitlines() if "relay-posted" in line][0]
    receiver.requests.clear()
    receiver.api[JOBS] = jobs_answer("failure")
    receiver.api["/repos/example-org/example/actions/jobs/55/logs"] = (
        302,
        {"Location": receiver.base + "/blobstore/log"},
        b"",
    )
    receiver.api["/blobstore/log"] = (200, {}, marker.encode())
    run = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver, extra_env=attempt_env(receiver))
    assert run.code == 0 and len(receiver.posts()) == 5
    gets = {r["path"]: r for r in receiver.requests if r.get("method") == "GET"}
    assert "authorization" in gets["/repos/example-org/example/actions/jobs/55/logs"]["headers"]
    assert "authorization" not in gets["/blobstore/log"]["headers"]


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", None])
def test_a_second_attempt_after_a_cancelled_or_skipped_job_posts_everything(receiver, tmp_path, conclusion):
    receiver.api[JOBS] = jobs_answer(conclusion)
    run = send_issue(tmp_path, receiver, extra_env=attempt_env(receiver))
    assert run.code == 0 and len(receiver.posts()) == 1


def test_when_github_cannot_be_asked_the_post_is_sent_anyway(receiver, tmp_path):
    run = send_issue(tmp_path, receiver, extra_env=attempt_env(receiver))  # the receiver answers 404
    assert run.code == 0 and len(receiver.posts()) == 1
    assert "could not be checked" in run.out


def test_the_marker_for_a_post_is_the_same_on_every_run(receiver, tmp_path):
    one = send_issue(tmp_path, receiver)
    two = send_issue(tmp_path, receiver)
    line = lambda run: [x for x in run.out.splitlines() if "relay-posted" in x]  # noqa: E731
    assert line(one) == line(two) and len(line(one)) == 1


# ---------------------------------------------------------------- the hand run


def dispatch(receiver, tmp_path, dry_run, secrets=None):
    payload = {"inputs": {"dry_run": dry_run}, "repository": {"full_name": "example-org/example"}}
    return run_relay(tmp_path, "workflow_dispatch", payload, receiver, secrets=secrets)


@pytest.mark.parametrize("value", ["true", True, None])
def test_a_dry_run_sends_nothing_and_shows_every_kind_of_post(receiver, tmp_path, value):
    run = dispatch(receiver, tmp_path, value)
    assert run.code == 0 and receiver.requests == []
    assert "dry run, DISCORD_WEBHOOK_RELEASES is set" in run.out
    for kind in ("New issue #1", "Merged: fix: a sample change", "Announcement:", "New question:"):
        assert kind in run.out
    assert "Dry run: nothing was sent" in run.out
    assert "~~~~json" in run.summary


def test_a_dry_run_reports_missing_secrets_by_name_only(receiver, tmp_path):
    run = dispatch(receiver, tmp_path, "true", secrets={})
    assert run.code == 0 and "DISCORD_WEBHOOK_FEED is missing" in run.out


@pytest.mark.parametrize("value", ["false", False])
def test_switching_the_dry_run_off_sends_one_test_line_to_the_feed(receiver, tmp_path, value):
    run = dispatch(receiver, tmp_path, value)
    assert run.code == 0
    posts = receiver.posts()
    assert len(posts) == 1 and posts[0]["secret"] == "DISCORD_WEBHOOK_FEED"
    assert posts[0]["payload"]["flags"] == 4096
    assert posts[0]["payload"]["allowed_mentions"] == {"parse": []}


# ---------------------------------------------------------------- the log and the summary


def test_no_address_or_token_ever_reaches_the_log_or_the_summary(receiver, tmp_path):
    receiver.script[FEED] = [answer(500)] * 5
    run = send_issue(tmp_path, receiver)
    ok = run_relay(tmp_path, RELEASE["event_name"], RELEASE["payload"], receiver)
    for out in (run.out, run.summary, ok.out, ok.summary):
        for token in TOKENS.values():
            assert token not in out
        assert HOOK_PATH not in out and "127.0.0.1" not in out


def test_an_unreadable_event_file_is_a_configuration_error(receiver, tmp_path):
    run = run_relay(tmp_path, "issues", {}, receiver, extra_env={"GITHUB_EVENT_PATH": str(tmp_path / "missing.json")})
    assert run.code == 2 and "::error title=Discord relay::" in run.out and receiver.requests == []


def test_a_broken_layout_is_a_configuration_error(receiver, tmp_path):
    layout = tmp_path / "broken.toml"
    layout.write_text("[relay]\nproject = 3\n")
    run = send_issue(tmp_path, receiver, layout=layout)
    assert run.code == 2 and receiver.requests == []


def test_an_event_type_that_is_not_relayed_is_a_clean_skip(receiver, tmp_path):
    run = run_relay(tmp_path, "pull_request", {"repository": {"full_name": "example-org/example"}}, receiver)
    assert run.code == 0 and "the event type is not relayed" in run.out and receiver.requests == []


# ---------------------------------------------------------------- what the script is


def test_the_script_imports_only_the_standard_library():
    tree = ast.parse(RELAY_FILE.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    assert modules and modules <= set(sys.stdlib_module_names), modules - set(sys.stdlib_module_names)


def relay_files():
    mine = [ROOT / "relay", FIXTURES]
    paths = [p for folder in mine for p in folder.rglob("*") if p.is_file() and p.suffix in (".py", ".json", ".toml")]
    return paths + sorted(Path(__file__).resolve().parent.glob("test_relay_*.py"))


def test_the_shared_code_names_no_project_and_holds_no_identifier():
    # the words are built from pieces so that this file passes the same check
    words = ("phae" + "mos", "melo" + "phos")
    address = re.compile(r"discord(?:app)?\.com/api/" + "webhooks/", re.IGNORECASE)
    for path in relay_files():
        text = path.read_text(encoding="utf-8")
        assert not any(word in text.lower() for word in words), path
        assert not re.search(r"\d{17,20}", text), path
        assert not address.search(text), path


# ---------------------------------------------------------------- layouts


def test_official_webhook_hosts_are_accepted_and_get_wait_true(monkeypatch):
    monkeypatch.delenv("RELAY_ALLOW_LOOPBACK", raising=False)
    for host in ("discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com"):
        url = relay.check_hook_url(f"https://{host}{HOOK_PATH}1/abc?wait=false&thread_id=5", "NAME")
        assert url.startswith(f"https://{host}{HOOK_PATH}1/abc?")
        assert "wait=true" in url and "wait=false" not in url


def test_a_project_with_no_releases_webhook_skips_a_release_cleanly(receiver, tmp_path):
    text = (FIXTURES / "layout.toml").read_text(encoding="utf-8")
    start = text.index('[[webhooks]]\nname = "Example releases"')
    layout = tmp_path / "no-releases.toml"
    layout.write_text(text[:start] + text[text.index("[[webhooks]]", start + 5) :], encoding="utf-8")
    run = run_relay(tmp_path, RELEASE["event_name"], RELEASE["payload"], receiver, layout=layout)
    assert run.code == 0 and receiver.requests == []
    assert "no webhook for the releases channel" in run.out


def test_every_real_layout_in_this_folder_loads_and_renders_each_sample(receiver, tmp_path):
    layouts = sorted((ROOT / "layout").glob("*.toml"))
    if not layouts:
        skip_loudly("no layout in this copy")
    for layout in layouts:
        cfg = relay.load_config(str(layout))
        assert cfg.webhooks and cfg.discussions and cfg.labels
        run = run_relay(tmp_path, "workflow_dispatch", {"inputs": {"dry_run": "true"}}, receiver, layout=layout)
        assert run.code == 0 and "dry run, DISCORD_WEBHOOK_FEED is set" in run.out
        assert receiver.requests == []


# ---------------------------------------------------------------- the hourly cap on the feed channel

RUNS_PATH = "/repos/example-org/example/actions/workflows/discord-relay.yml/runs"
NOW = 1_800_000_000.0


def cap_env(receiver):
    return {**attempt_env(receiver, 1, "99"), "GITHUB_RUN_ID": "99"}


def posted_line(n, secret="DISCORD_WEBHOOK_FEED"):
    return f"2026-12-01T10:00:00.000Z relay: relay-posted {n:016x} issue {n} to {secret} with status 200"


def history(receiver, logs, total=None, current=99):
    """Answers for the workflow's recent runs. Each log is the text of one earlier run."""
    runs = [{"id": 100 + i} for i in range(len(logs))] + [{"id": current}]
    receiver.api[RUNS_PATH] = (200, {}, json.dumps({"total_count": total or len(runs), "workflow_runs": runs}).encode())
    for i, log in enumerate(logs):
        receiver.api[f"/repos/example-org/example/actions/runs/{100 + i}/jobs"] = (
            200,
            {},
            json.dumps({"jobs": [{"id": 500 + i, "name": "relay"}]}).encode(),
        )
        receiver.api[f"/repos/example-org/example/actions/jobs/{500 + i}/logs"] = (200, {}, log.encode())


def run_many(tmp_path, receiver, monkeypatch, **kwargs):
    monkeypatch.setattr(relay, "_wall", lambda: NOW)
    return run_relay(
        tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver, extra_env=cap_env(receiver), **kwargs
    )


def test_the_cap_is_ten_feed_posts_an_hour():
    assert relay.FEED_CAP_PER_HOUR == 10 and relay.CAP_WINDOW_SECONDS == 3600


def test_under_the_cap_everything_is_posted_and_no_notice_is_sent(receiver, tmp_path, monkeypatch):
    history(receiver, ["\n".join(posted_line(n) for n in range(4))])
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0 and len(receiver.posts()) == 6
    assert "held back" not in run.out


def test_the_log_window_is_one_hour_and_the_current_run_is_not_counted(receiver, tmp_path, monkeypatch):
    history(receiver, [posted_line(1)])
    run_many(tmp_path, receiver, monkeypatch)
    listing = [r for r in receiver.requests if r.get("path") == RUNS_PATH][0]
    assert "created=%3E%3D2027-01-15T07%3A00%3A00Z" in listing["query"]  # 3,600 seconds before the fixed clock
    jobs_calls = [r["path"] for r in receiver.requests if r["path"].endswith("/jobs")]
    assert "/repos/example-org/example/actions/runs/99/jobs" not in jobs_calls


def test_a_burst_over_the_cap_posts_what_fits_and_one_line_about_the_rest(receiver, tmp_path, monkeypatch):
    history(receiver, ["\n".join(posted_line(n) for n in range(7))])
    run = run_many(tmp_path, receiver, monkeypatch)
    posts = receiver.posts()
    assert run.code == 0 and len(posts) == 4  # three posts and the one line
    assert "3 more new items are held back" in posts[-1]["payload"]["content"]
    assert posts[-1]["payload"]["allowed_mentions"] == {"parse": []} and posts[-1]["payload"]["flags"] == 4096
    assert "held back by the hourly cap" in run.summary and "relay-held-notice" in run.out


def test_over_the_cap_already_posts_only_the_notice(receiver, tmp_path, monkeypatch):
    history(receiver, ["\n".join(posted_line(n) for n in range(10))])
    run = run_many(tmp_path, receiver, monkeypatch)
    posts = receiver.posts()
    assert run.code == 0 and len(posts) == 1 and "6 more new items are held back" in posts[0]["payload"]["content"]


def test_the_notice_is_posted_once_an_hour(receiver, tmp_path, monkeypatch):
    log = "\n".join(posted_line(n) for n in range(10)) + "\nrelay: relay-held-notice posted with status 200"
    history(receiver, [log])
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0 and receiver.posts() == []
    assert "held back by the cap" in run.out


def test_only_feed_posts_are_counted_and_releases_are_never_capped(receiver, tmp_path, monkeypatch):
    history(receiver, ["\n".join(posted_line(n, "DISCORD_WEBHOOK_RELEASES") for n in range(30))])
    assert run_many(tmp_path, receiver, monkeypatch).code == 0 and len(receiver.posts()) == 6
    receiver.requests.clear()
    history(receiver, ["\n".join(posted_line(n) for n in range(30))])
    release = run_relay(tmp_path, RELEASE["event_name"], RELEASE["payload"], receiver, extra_env=cap_env(receiver))
    assert release.code == 0 and [p["secret"] for p in receiver.posts()] == ["DISCORD_WEBHOOK_RELEASES"]
    assert not [r for r in receiver.requests if r.get("path") == RUNS_PATH]


def test_when_the_recent_runs_cannot_be_read_the_feed_is_held_and_the_run_fails(receiver, tmp_path, monkeypatch):
    receiver.api[RUNS_PATH] = (500, {}, b"{}")
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 1 and receiver.posts() == []
    assert "could not be counted" in run.out


def test_more_runs_than_can_be_counted_is_the_cap_reached_not_an_error(receiver, tmp_path, monkeypatch):
    history(receiver, [posted_line(1)], total=500)
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0
    posts = receiver.posts()
    assert len(posts) == 1 and "held back" in posts[0]["payload"]["content"]
    assert "Too many recent runs" in run.out and "held back by the hourly cap" in run.summary


def test_without_a_token_the_cap_is_not_checked_and_says_so(receiver, tmp_path):
    run = run_relay(tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver)
    assert run.code == 0 and len(receiver.posts()) == 6 and "cap on the feed channel was not checked" in run.out


def test_a_second_attempt_does_not_count_its_own_earlier_posts_twice(receiver, tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "_wall", lambda: NOW)
    first = run_relay(
        tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver, extra_env=attempt_env(receiver, 1)
    )
    markers = [x for x in first.out.splitlines() if "relay-posted" in x]
    receiver.requests.clear()
    receiver.api[JOBS] = jobs_answer("failure")
    receiver.api["/repos/example-org/example/actions/jobs/55/logs"] = (200, {}, "\n".join(markers).encode())
    again = run_relay(
        tmp_path, PUSH_MANY["event_name"], PUSH_MANY["payload"], receiver, extra_env=attempt_env(receiver, 2)
    )
    assert again.code == 0 and receiver.posts() == []


# ---------------------------------------------------------------- floods, time limits and releases


def quiet_log(n):
    return f"2026-12-01T10:00:00.000Z relay: nothing to post: held until a maintainer acts {n}"


def test_sixty_runs_in_the_window_hold_the_next_feed_post_with_one_notice_and_exit_zero(
    receiver, tmp_path, monkeypatch
):
    history(receiver, [quiet_log(n) for n in range(60)])
    run = run_many(tmp_path, receiver, monkeypatch)
    posts = receiver.posts()
    assert run.code == 0
    assert len(posts) == 1 and "6 more new items are held back" in posts[0]["payload"]["content"]
    assert [p for p in posts if "Merged" in p["payload"]["content"]] == []


def test_a_flood_never_makes_a_run_fail(receiver, tmp_path, monkeypatch):
    for size in (51, 80, 500):
        receiver.requests.clear()
        history(receiver, [quiet_log(n) for n in range(min(size, 60))], total=size)
        assert run_many(tmp_path, receiver, monkeypatch).code == 0


def test_the_notice_is_not_repeated_when_a_scanned_run_already_posted_it(receiver, tmp_path, monkeypatch):
    logs = ["relay: relay-held-notice posted with status 200"] + [quiet_log(n) for n in range(59)]
    history(receiver, logs)
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0 and receiver.posts() == []


def test_only_runs_that_posted_are_counted_so_held_runs_do_not_use_up_the_cap(receiver, tmp_path, monkeypatch):
    history(receiver, [quiet_log(n) for n in range(45)] + [posted_line(1)])
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0 and len(receiver.posts()) == 6


def test_the_count_has_a_deadline_and_holds_the_post_when_it_runs_out(receiver, tmp_path, monkeypatch):
    history(receiver, [quiet_log(n) for n in range(20)])
    original, clock = relay.api_get, [0.0]

    def slow(path, token):
        clock[0] += 30
        return original(path, token)

    monkeypatch.setattr(relay, "api_get", slow)
    run = run_many(tmp_path, receiver, monkeypatch, clock=clock)
    assert run.code == 0 and "Too many recent runs" in run.out
    assert len([r for r in receiver.requests if r.get("method") == "GET"]) <= 5
    assert all("Merged" not in p["payload"]["content"] for p in receiver.posts())


def test_the_count_has_a_ceiling_on_calls(receiver, tmp_path, monkeypatch):
    history(receiver, [quiet_log(n) for n in range(20)])
    monkeypatch.setattr(relay, "MAX_COUNT_CALLS", 7)
    run = run_many(tmp_path, receiver, monkeypatch)
    assert run.code == 0 and len([r for r in receiver.requests if r.get("method") == "GET"]) <= 7


def test_a_release_posts_while_the_feed_is_flooded_and_capped(receiver, tmp_path, monkeypatch):
    history(receiver, [posted_line(n) for n in range(40)], total=500)
    monkeypatch.setattr(relay, "_wall", lambda: NOW)
    run = run_relay(tmp_path, RELEASE["event_name"], RELEASE["payload"], receiver, extra_env=cap_env(receiver))
    assert run.code == 0
    assert [p["secret"] for p in receiver.posts()] == ["DISCORD_WEBHOOK_RELEASES"]
    assert not [r for r in receiver.requests if r.get("path") == RUNS_PATH], "a release never counts runs"
    announcement = json.loads((FIXTURES / "events" / "discussion_announcement.json").read_text())
    receiver.requests.clear()
    run_relay(tmp_path, announcement["event_name"], announcement["payload"], receiver, extra_env=cap_env(receiver))
    assert [p["secret"] for p in receiver.posts()] == ["DISCORD_WEBHOOK_ANNOUNCEMENTS"]


def test_a_stranger_template_label_is_a_quiet_exit_zero(receiver, tmp_path):
    for name in ("issue_labeled_by_stranger_template_404_held", "issue_labeled_template_enhancement_404_held"):
        recorded = json.loads((FIXTURES / "events" / f"{name}.json").read_text())
        run = run_relay(
            tmp_path, recorded["event_name"], recorded["payload"], receiver, extra_env=api_env(recorded, receiver)
        )
        assert run.code == 0 and receiver.posts() == [] and "::error" not in run.out


@pytest.mark.parametrize("answer", [(403, {}, b"{}"), (500, {}, b"{}"), (502, {}, b"{}"), (None, {}, b"")])
def test_a_real_inability_to_ask_github_fails_the_run_and_posts_nothing(monkeypatch, answer):
    monkeypatch.setattr(relay, "api_get", lambda path, token: answer)
    gate = relay.Gate("t", "example-org/example")
    with pytest.raises(relay.GateError):
        gate.can_write("maintainer-one")


def test_not_found_means_cannot_write(monkeypatch):
    monkeypatch.setattr(relay, "api_get", lambda path, token: (404, {}, b'{"message": "Resource not found"}'))
    assert relay.Gate("t", "example-org/example").can_write("passer-by") is False


def test_only_owner_is_trusted_without_a_permission_check():
    assert relay.may_release("OWNER", "x", None) is True
    for association in ("MEMBER", "COLLABORATOR", "NONE", None):
        assert relay.may_release(association, "x", None) is False
