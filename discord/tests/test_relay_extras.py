"""The relay's later additions: the good first issue lead, forum posting, categories named in words and CI alerts."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import FIXTURES, HOOK_PATH, TOKENS, receiver, relay, run_relay  # noqa: E402,F401

BASE_LAYOUT = (FIXTURES / "layout.toml").read_text()
CI_TOKEN = "citoken1234567"


def with_ci_layout(tmp_path: Path, ideas: str = "") -> Path:
    """The stand-in layout with a CI alerts webhook and optionally a different route for Ideas."""
    text = BASE_LAYOUT.replace(
        '[[webhooks]]\nname = "Reports"',
        '[[webhooks]]\nname = "Example CI alerts"\nchannel = "ci-alerts"\n'
        'secret = "DISCORD_WEBHOOK_CI_ALERTS"\nstore = "github"\n\n[[webhooks]]\nname = "Reports"',
    )
    text = text.replace(
        'research = { webhook = "Example on GitHub", lead = "New research note" }',
        'research = { webhook = "Example on GitHub", lead = "New research note in Research" }',
    )
    if ideas:
        text = text.replace('ideas = { webhook = "Example on GitHub", lead = "New idea" }', ideas.strip())
    path = tmp_path / "layout.toml"
    path.write_text(text)
    return path


def event(name: str) -> dict:
    return json.loads((FIXTURES / "events" / f"{name}.json").read_text())["payload"]


def issue_with(labels: list[str], association: str = "OWNER") -> dict:
    payload = copy.deepcopy(event("issue_opened_labels"))
    payload["issue"]["labels"] = [{"name": n} for n in labels]
    payload["issue"]["author_association"] = association
    return payload


# ---- good first issue ---------------------------------------------------------------------------------------------


def test_an_issue_marked_good_first_issue_has_its_own_lead(receiver, tmp_path):
    run = run_relay(tmp_path, "issues", issue_with(["bug", "good first issue"]), receiver)
    assert run.code == 0
    content = receiver.posts()[0]["payload"]["content"]
    assert content.startswith("Good first issue #412: ")
    assert "Labels: bug, good first issue." in content


def test_the_good_first_lead_ignores_case_and_a_plain_issue_keeps_its_lead(receiver, tmp_path):
    run_relay(tmp_path, "issues", issue_with(["Good First Issue"]), receiver)
    assert receiver.posts()[0]["payload"]["content"].startswith("Good first issue #412")
    receiver.requests.clear()
    run_relay(tmp_path, "issues", issue_with(["bug"]), receiver)
    assert receiver.posts()[0]["payload"]["content"].startswith("New issue #412")


def test_a_good_first_issue_from_a_stranger_still_waits_for_a_maintainer(receiver, tmp_path):
    run = run_relay(tmp_path, "issues", issue_with(["good first issue"], "NONE"), receiver)
    assert run.code == 0 and receiver.posts() == []


# ---- categories named in words -------------------------------------------------------------------------------------


def test_ideas_and_research_reach_the_feed_with_their_category_in_words(receiver, tmp_path):
    layout = with_ci_layout(tmp_path)
    for name, words in (("discussion_research", "New research note in Research: "),):
        run_relay(tmp_path, "discussion", event(name), receiver, layout=layout)
        post = receiver.posts()[-1]
        assert post["secret"] == "DISCORD_WEBHOOK_FEED"
        assert post["payload"]["content"].startswith(words)
        assert post["payload"]["allowed_mentions"] == {"parse": []}


def test_the_real_layouts_name_each_category_in_the_lead():
    from conftest import ROOT

    text = next((ROOT / "layout").glob("*.toml")).read_text()
    for lead in (
        "New idea in Ideas",
        "New research note in Research",
        "New question in Q&A",
        "New build shared in Show and tell",
        "New poll in Polls",
    ):
        assert f'lead = "{lead}"' in text


# ---- posting into a forum ------------------------------------------------------------------------------------------


def test_a_route_to_a_forum_names_the_post(receiver, tmp_path):
    layout = with_ci_layout(
        tmp_path, 'ideas = { webhook = "Example on GitHub", lead = "New idea in Ideas", thread = true }'
    )
    run_relay(tmp_path, "discussion", event("discussion_ideas"), receiver, layout=layout)
    payload = receiver.posts()[-1]["payload"]
    assert payload["thread_name"] == "A weekly digest email"
    assert payload["content"].startswith("New idea in Ideas: ")
    assert payload["allowed_mentions"] == {"parse": []}


def test_a_forum_post_name_is_cut_to_the_limit_and_holds_no_mention(receiver, tmp_path):
    layout = with_ci_layout(
        tmp_path, 'ideas = { webhook = "Example on GitHub", lead = "New idea in Ideas", thread = true }'
    )
    payload = event("discussion_ideas")
    payload["discussion"]["title"] = "@everyone " + "long " * 60
    run_relay(tmp_path, "discussion", payload, receiver, layout=layout)
    name = receiver.posts()[-1]["payload"]["thread_name"]
    assert len(name) <= 100 and "@everyone" not in name and "@" + relay.ZWSP in name


def test_a_route_to_a_text_channel_sends_no_thread_name(receiver, tmp_path):
    run_relay(tmp_path, "discussion", event("discussion_ideas"), receiver)
    assert "thread_name" not in receiver.posts()[-1]["payload"]


# ---- CI alerts -------------------------------------------------------------------------------------------------------


def alerts(receiver):
    return [r for r in receiver.requests if r.get("method") != "GET" and r["path"].endswith(CI_TOKEN)]


def test_a_failed_run_on_the_default_branch_alerts_staff_with_fixed_words_and_a_link(receiver, tmp_path):
    run = run_ci_main(tmp_path, receiver)
    assert run.code == 0, run.out
    [post] = alerts(receiver)
    content = post["json"]["content"]
    assert content == "CI failed on main: run 123456. <https://github.com/example-org/example/actions/runs/123456>"
    assert post["json"]["allowed_mentions"] == {"parse": []}
    assert set(post["json"]) == {"username", "content", "allowed_mentions"}


def run_ci_main(tmp_path, receiver, event_name="push", env=None, payload=None, layout=None):
    """Runs the poster with the --ci-failure switch."""
    import contextlib
    import io
    import os
    from unittest import mock

    layout = layout or with_ci_layout(tmp_path)
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps(
            payload
            if payload is not None
            else {"repository": {"full_name": "example-org/example", "default_branch": "main"}}
        )
    )
    summary = tmp_path / "summary.md"
    summary.write_text("")
    environment = {
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_STEP_SUMMARY": str(summary),
        "RELAY_ALLOW_LOOPBACK": "1",
        "PATH": os.environ.get("PATH", ""),
        "GITHUB_REPOSITORY": "example-org/example",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ID": "123456",
        "GITHUB_WORKFLOW": "CI",
        "DISCORD_WEBHOOK_CI_ALERTS": f"{receiver.base}{HOOK_PATH}{CI_TOKEN}",
    }
    environment.update(env or {})
    buffer = io.StringIO()
    with (
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(relay, "_sleep", lambda s: None),
        contextlib.redirect_stdout(buffer),
    ):
        code = relay.main(["--layout", str(layout), "--ci-failure"])

    class Done:
        pass

    done = Done()
    done.code, done.out = code, buffer.getvalue()
    return done


def test_a_pull_request_is_never_alerted_even_from_the_default_branch_name(receiver, tmp_path):
    for name in ("pull_request", "pull_request_target", "workflow_run"):
        run = run_ci_main(tmp_path, receiver, event_name=name)
        assert run.code == 0 and "nothing to post" in run.out
    assert alerts(receiver) == []


def test_a_push_to_another_branch_or_another_repository_is_not_alerted(receiver, tmp_path):
    run_ci_main(tmp_path, receiver, env={"GITHUB_REF": "refs/heads/feature"})
    run_ci_main(tmp_path, receiver, env={"GITHUB_REF": "refs/pull/5/merge"})
    run_ci_main(tmp_path, receiver, env={"GITHUB_REPOSITORY": "someone-else/fork"})
    assert alerts(receiver) == []


def test_the_alert_holds_nothing_from_a_log_or_the_environment_but_the_fixed_words(receiver, tmp_path):
    secret = "a-secret-that-a-log-might-hold"
    run_ci_main(tmp_path, receiver, env={"GITHUB_WORKFLOW": "CI—" + secret, "LOG_TAIL": secret, "MY_TOKEN": secret})
    [post] = alerts(receiver)
    text = json.dumps(post["json"])
    assert "run 123456" in text
    assert "MY_TOKEN" not in text and "LOG_TAIL" not in text
    assert secret not in text, "no workflow name, log or environment text is ever copied"


def test_a_bad_run_number_fails_the_run_and_posts_nothing(receiver, tmp_path):
    run = run_ci_main(tmp_path, receiver, env={"GITHUB_RUN_ID": "12; rm -rf"})
    assert run.code == 1 and alerts(receiver) == []


def test_without_the_webhook_secret_it_is_a_notice_and_a_clean_exit(receiver, tmp_path):
    run = run_ci_main(tmp_path, receiver, env={"DISCORD_WEBHOOK_CI_ALERTS": ""})
    assert run.code == 0 and alerts(receiver) == []


def test_a_layout_without_a_ci_channel_posts_nothing(receiver, tmp_path):
    run = run_ci_main(tmp_path, receiver, layout=FIXTURES / "layout.toml")
    assert run.code == 0 and "no webhook for the CI alerts channel" in run.out


def test_the_ci_alert_goes_only_to_the_ci_secret(receiver, tmp_path):
    run_ci_main(tmp_path, receiver)
    assert [r["path"].rsplit("/", 1)[-1] for r in receiver.requests if r.get("method") != "GET"] == [CI_TOKEN]
    assert set(TOKENS.values()).isdisjoint({CI_TOKEN})


# ---- the real layout: Ideas and Research become forum posts -----------------------------------------------------------


def real_layout():
    from conftest import ROOT

    return next((ROOT / "layout").glob("*.toml"))


def test_a_new_ideas_or_research_discussion_becomes_a_forum_post_in_its_own_channel(receiver, tmp_path):
    cfg = relay.load_config(str(real_layout()))
    for name, secret, lead in (
        ("discussion_ideas", "DISCORD_WEBHOOK_IDEAS", "New idea in Ideas: "),
        ("discussion_research", "DISCORD_WEBHOOK_RESEARCH", "New research note in Research: "),
    ):
        raw = json.loads((FIXTURES / "events" / f"{name}.json").read_text())["payload"]
        raw["repository"]["full_name"] = cfg.repository
        result = relay.build_posts("discussion", raw, cfg)
        [post] = result.posts
        assert post.webhook_var == secret and post.webhook_var != "DISCORD_WEBHOOK_FEED"
        assert post.payload["thread_name"] == raw["discussion"]["title"]
        assert post.payload["content"].startswith(lead)
        assert (
            f"<https://github.com/{cfg.repository}/discussions/{raw['discussion']['number']}>"
            in post.payload["content"]
        )
        assert post.payload["allowed_mentions"] == {"parse": []}


def test_the_other_categories_still_go_to_the_feed_as_one_line(receiver, tmp_path):
    cfg = relay.load_config(str(real_layout()))
    raw = json.loads((FIXTURES / "events" / "discussion_qa.json").read_text())["payload"]
    raw["repository"]["full_name"] = cfg.repository
    [post] = relay.build_posts("discussion", raw, cfg).posts
    assert post.webhook_var == "DISCORD_WEBHOOK_FEED" and "thread_name" not in post.payload
    assert post.payload["content"].startswith("New question in Q&A: ")


# ---- a forum that requires a tag ---------------------------------------------------------------------------------------

TAGGED = 'ideas = { webhook = "Example on GitHub", lead = "New idea in Ideas", thread = true, tag = "From GitHub", tag_secret = "DISCORD_TAG_IDEAS" }'


def test_a_forum_post_carries_the_tag_id_from_its_secret(receiver, tmp_path):
    layout = with_ci_layout(tmp_path, TAGGED)
    run = run_relay(
        tmp_path, "discussion", event("discussion_ideas"), receiver, layout=layout,
        extra_env={"DISCORD_TAG_IDEAS": " 1234567 "},
    )  # fmt: skip
    assert run.code == 0
    payload = receiver.posts()[-1]["payload"]
    assert payload["applied_tags"] == ["1234567"] and "thread_name" in payload


def test_a_forum_post_with_no_tag_secret_is_not_sent_and_the_run_fails(receiver, tmp_path):
    layout = with_ci_layout(tmp_path, TAGGED)
    run = run_relay(tmp_path, "discussion", event("discussion_ideas"), receiver, layout=layout)
    assert run.code == 1 and receiver.posts() == []
    assert "DISCORD_TAG_IDEAS" in run.out


def test_a_tag_secret_that_is_not_a_number_is_refused(receiver, tmp_path):
    layout = with_ci_layout(tmp_path, TAGGED)
    run = run_relay(
        tmp_path, "discussion", event("discussion_ideas"), receiver, layout=layout,
        extra_env={"DISCORD_TAG_IDEAS": "not a tag"},
    )  # fmt: skip
    assert run.code == 1 and receiver.posts() == []


def test_the_real_layouts_give_every_forum_route_a_tag_that_the_forum_has():
    from conftest import ROOT
    from serverkit.layout import load

    layout = load(next((ROOT / "layout").glob("*.toml")))
    routes = {s: r for s, r in layout.relay["discussions"].items() if r.get("thread")}
    assert set(routes) == {"ideas", "research"}
    for route in routes.values():
        hook = next(h for h in layout.webhooks if h["name"] == route["webhook"])
        tags = [t["name"] for t in layout.channel(hook["channel"]).forum["tags"]]
        assert route["tag"] in tags and route["tag_secret"].startswith("DISCORD_TAG_")
