"""Rate limits, retries, partial failure and resuming after an interruption."""

from __future__ import annotations

import re
from collections import Counter

import pytest
from helpers import methods

STEPS = {
    "settings": (r"/guilds/\d+$", "PATCH"),
    "roles": (r"/roles$", "POST"),
    "channels": (r"/channels$", "POST"),
    "automod": (r"/auto-moderation/rules$", "POST"),
    "onboarding": (r"/onboarding$", "PUT"),
    "messages": (r"/channels/\d+/messages$", "POST"),
    "webhooks": (r"/webhooks$", "POST"),
    "commands": (r"/commands$", "PUT"),
}


def no_duplicates(fake):
    for label, names in (
        ("channels", [(c["name"], c["type"]) for c in fake.channels.values()]),
        ("roles", [r["name"] for r in fake.roles.values()]),
        ("webhooks", [h["name"] for h in fake.webhooks.values()]),
        ("rules", [r["name"] for r in fake.automod.values()]),
    ):
        repeated = [n for n, c in Counter(names).items() if c > 1]
        assert not repeated, (label, repeated)


@pytest.mark.parametrize("step", list(STEPS))
def test_an_interruption_at_each_step_stops_with_exit_1_and_the_next_run_finishes_cleanly(server, step):
    pattern, method = STEPS[step]
    server.fake.fail_next(pattern, "500", times=999, method=method)
    first = server.apply()
    assert first.code == 1, first.out + first.err
    assert "Not applied:" in first.out
    assert not re.search(r"\d{17,20}", first.out + first.err)
    server.fake.faults.clear()
    second = server.apply()
    assert second.code == 0, second.out + second.err
    assert server.plan().code == 0
    no_duplicates(server.fake)
    before = server.fake.write_count
    assert server.apply().code == 0 and server.fake.write_count == before


def test_an_interruption_reports_what_was_applied_and_what_was_not(server):
    server.fake.fail_next(r"/auto-moderation/rules$", "500", times=999, method="POST")
    result = server.apply()
    assert "Applied " in result.out and "Not applied:" in result.out
    applied = int(re.search(r"Applied (\d+) changes", result.out).group(1))
    assert applied > 20
    assert result.out.count("waiting") > 5


@pytest.mark.parametrize(
    "pattern", [r"/guilds/\d+/channels$", r"/guilds/\d+/roles$", r"/channels/\d+/webhooks$", r"/auto-moderation/rules$"]
)
def test_a_create_whose_answer_was_lost_is_not_made_twice(server, pattern):
    server.fake.fail_next(pattern, "lost", times=1, method="POST")
    result = server.apply()
    assert result.code == 0, result.out + result.err
    no_duplicates(server.fake)
    assert server.plan().code == 0


def test_a_dropped_connection_is_tried_again(server):
    server.fake.fail_next(r"/guilds/\d+/channels$", "drop", times=2, method="POST")
    assert server.apply().code == 0
    no_duplicates(server.fake)


def test_a_short_server_error_on_an_update_is_retried_with_a_growing_wait(server):
    assert server.apply().code == 0
    server.fake.by_name("general")["topic"] = "drift"
    server.fake.fail_next(r"/channels/\d+$", "500", times=2, method="PATCH")
    server.fake.clock.slept.clear()
    assert server.apply().code == 0
    assert server.fake.clock.slept[:2] == [1, 2]


# ---- rate limits -----------------------------------------------------------------------------------------


def test_a_bucket_with_a_small_limit_is_never_exceeded(server):
    fake = server.fake
    fake.limit("POST /guilds/:id/channels", 3, 5.0)
    assert server.apply().code == 0
    assert fake.rejections == 0, "the script read the headers and waited before the bucket was empty"
    assert sum(fake.clock.slept) > 5


def test_a_bucket_shared_by_two_routes_is_never_exceeded(server):
    fake = server.fake
    fake.limit("POST /guilds/:id/channels", 4, 5.0, bucket="shared")
    fake.limit("POST /guilds/:id/roles", 4, 5.0, bucket="shared")
    assert server.apply().code == 0
    # the first request on a route whose bucket is not yet known can meet a bucket that another route emptied
    assert fake.rejections <= 1


def test_a_global_limit_that_the_script_cannot_see_coming_is_waited_out(server):
    fake = server.fake
    fake.global_limit = (15, 2.0)
    assert server.apply().code == 0
    assert fake.rejections > 0
    assert min(fake.clock.slept) > 0
    assert server.plan().code == 0


def test_the_retry_after_value_is_honoured_and_capped_at_five_tries(server):
    fake = server.fake
    fake.fail_next(r"/users/@me$", "429", times=2)
    assert server.plan().code == 4
    assert all(s >= 1 for s in fake.clock.slept[:2])
    fake.clock.slept.clear()
    fake.fail_next(r"/users/@me$", "429", times=99)
    result = server.plan()
    assert result.code == 1 and "rate limited" in result.err
    assert len(fake.clock.slept) == 5
    assert methods(fake) == set()


def test_the_run_stops_when_waiting_would_pass_max_wait(server):
    fake = server.fake
    fake.limit("POST /guilds/:id/channels", 1, 100.0)
    result = server.apply("--max-wait", "30")
    assert result.code == 1
    assert "would pass 30 seconds" in result.out
    assert sum(fake.clock.slept) <= 30
    fake.limit("POST /guilds/:id/channels", 1, 10.0)
    assert server.apply().code == 0


def test_the_third_refusal_for_missing_permission_stops_the_run(server):
    fake = server.fake
    fake.fail_next(r"/x$", "500", times=0)
    # every write answers 403 once the bot loses manage_channels after the roles are made
    from fake_discord import BITS

    seen = {"n": 0}

    def strip(f):
        seen["n"] += 1
        # once the first channels exist, the bot loses the permission to make or change more
        if seen["n"] > 1 and len(f.channels) >= 2 and not seen.get("done"):
            seen["done"] = True
            f.roles[f.bot_role_id]["permissions"] = str(
                int(f.roles[f.bot_role_id]["permissions"]) & ~BITS["manage_channels"]
            )

    fake.after_write = strip
    result = server.apply()
    assert result.code == 1
    assert "manage_channels" in result.out
    stops = [r for r in fake.requests if r[2] == 403]
    assert 1 <= len(stops) <= 3
