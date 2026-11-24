"""A static check of the relay workflow, which is a security boundary.

It parses the workflow file and fails when a shell line holds an expression, when an
action is not pinned to a full commit hash, when a permission is wider than the
specification gives, when a trigger appears that the specification does not list or
when a secret can reach a step that should not hold one. The checks are run against
mutated copies as well, so the checker itself is known to catch each fault.

These tests need the monorepo. In the published copy of discord/ there is no workflow, so
this module says so in a warning and skips as a whole. The checks that hold in both places
(no workflow inside this folder) live in test_relay_copy.py and always run.
"""

from __future__ import annotations

import copy
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_miniyaml import load, parse  # noqa: E402
from test_relay_support import ROOT, skip_loudly  # noqa: E402

MONOREPO = ROOT.parent
WORKFLOW = MONOREPO / ".github" / "workflows" / "discord-relay.yml"

if not WORKFLOW.is_file():
    skip_loudly(
        "the workflow checks need the monorepo: no .github/workflows/discord-relay.yml above this folder", module=True
    )

SHA_PIN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
# the only values an expression may read: numbers, the event name, the commit, the token
# and the three webhook secrets. None of them is text that a stranger writes.
SAFE_TERMS = (
    r"github\.event_name",
    r"github\.sha",
    r"github\.token",
    r"github\.repository",
    r"github\.event\.release\.id",
    r"github\.event\.issue\.number",
    r"github\.event\.discussion\.number",
    r"secrets\.DISCORD_WEBHOOK_(?:ANNOUNCEMENTS|RELEASES|FEED|IDEAS|RESEARCH)",
    r"secrets\.DISCORD_TAG_(?:IDEAS|RESEARCH)",
)
WEBHOOK_SECRETS = {
    "DISCORD_WEBHOOK_ANNOUNCEMENTS",
    "DISCORD_WEBHOOK_RELEASES",
    "DISCORD_WEBHOOK_FEED",
    "DISCORD_WEBHOOK_IDEAS",
    "DISCORD_WEBHOOK_RESEARCH",
    # the forums need a tag on every new post, so the poster is given the tag ids
    "DISCORD_TAG_IDEAS",
    "DISCORD_TAG_RESEARCH",
}
ALLOWED_PERMISSIONS = {"contents": "read", "actions": "read"}
EXPECTED_ON = {
    "release": {"types": ["released"]},
    "issues": {"types": ["opened", "labeled"]},
    "discussion": {"types": ["created"]},
    "discussion_comment": {"types": ["created"]},
    "push": {"branches": ["main"]},
}


def walk(value: Any, path: str = ""):
    """Yields every string in a document with where it was found."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


def violations(doc: dict[str, Any], raw: str) -> list[str]:
    found: list[str] = []
    on = doc.get("on")
    if not isinstance(on, dict):
        return ["the workflow has no triggers"]
    # triggers
    unexpected = set(on) - set(EXPECTED_ON) - {"workflow_dispatch"}
    if unexpected:
        found.append(f"a trigger the specification does not list: {sorted(unexpected)}")
    for name, expected in EXPECTED_ON.items():
        if on.get(name) != expected:
            found.append(f"trigger {name} is {on.get(name)} and must be exactly {expected}")
    dispatch = on.get("workflow_dispatch")
    if not isinstance(dispatch, dict) or set(dispatch.get("inputs", {})) != {"dry_run"}:
        found.append("workflow_dispatch must take the one input dry_run")
    elif (
        dispatch["inputs"]["dry_run"].get("type") != "boolean"
        or dispatch["inputs"]["dry_run"].get("default") is not True
    ):
        found.append("dry_run must be a boolean that defaults to on")
    # permissions
    if doc.get("permissions") != {}:
        found.append("the workflow level permissions must be empty")
    jobs = doc.get("jobs") or {}
    if set(jobs) != {"relay"}:
        found.append(f"the workflow must hold the one job relay, it has {sorted(jobs)}")
    for name, job in jobs.items():
        if job.get("permissions") != ALLOWED_PERMISSIONS:
            found.append(f"job {name} permissions are {job.get('permissions')}, not {ALLOWED_PERMISSIONS}")
        if not isinstance(job.get("timeout-minutes"), int) or job["timeout-minutes"] > 3:
            found.append(f"job {name} needs a time-out of 3 minutes or less")
        concurrency = job.get("concurrency")
        if not isinstance(concurrency, dict) or not str(concurrency.get("group", "")).startswith("discord-relay-"):
            found.append(f"job {name} needs a concurrency group that starts with discord-relay-")
        elif concurrency.get("cancel-in-progress") is not False:
            found.append(f"job {name} must never cancel a run in progress")
        if job.get("environment") != "community":
            found.append(f"job {name} must name the community environment")
        if not re.fullmatch(r"github\.repository == '[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'", str(job.get("if", ""))):
            found.append(f"job {name} needs the repository guard")
        if "env" in job or "env" in doc:
            found.append("secrets and tokens belong to the one step that posts, never to a job or the workflow")
        for index, step in enumerate(job.get("steps") or []):
            where = f"{name} step {index + 1}"
            if "uses" in step:
                if not SHA_PIN.match(str(step["uses"])):
                    found.append(f"{where}: {step['uses']} is not pinned to a full commit hash")
                if str(step["uses"]).startswith("actions/checkout@"):
                    with_ = step.get("with") or {}
                    if with_.get("persist-credentials") is not False:
                        found.append(f"{where}: checkout must set persist-credentials to false")
                    if with_.get("ref") != "main":
                        found.append(f"{where}: checkout must always read main")
                    if with_.get("sparse-checkout") != "discord":
                        found.append(f"{where}: checkout must be sparse and hold discord only")
            if "run" in step:
                if "${{" in str(step["run"]):
                    found.append(f"{where}: a run line holds an expression")
                if re.search(r"github\.event|secrets\.|\bgh\b.*--body|\beval\b", str(step["run"])):
                    found.append(f"{where}: a run line reads event data or a secret")
            env = step.get("env") or {}
            holds_secret = any("secrets." in str(value) or "github.token" in str(value) for value in env.values())
            if holds_secret and "run" not in step:
                found.append(f"{where}: a secret reaches a step that is not the poster")
            if "uses" in step and holds_secret:
                found.append(f"{where}: a secret reaches an action")
            if holds_secret and {k for k in env if k != "GITHUB_TOKEN"} != WEBHOOK_SECRETS:
                found.append(f"{where}: the poster must get exactly the expected webhook and tag secrets and the token")
    # expressions: only the safe terms
    for where, text in walk(doc):
        for expression in EXPRESSION.findall(text):
            for term in expression.split("||"):
                if not re.fullmatch(r"\s*(?:" + "|".join(SAFE_TERMS) + r")\s*", term):
                    found.append(f"{where}: the expression {term.strip()!r} is not on the safe list")
    # pins carry their version in a comment
    for line in raw.splitlines():
        if re.search(r"\buses:\s", line) and not re.search(r"@[0-9a-f]{40} # v\d+(?:\.\d+){0,2}\s*$", line):
            found.append(f"a pin has no version comment: {line.strip()}")
    return found


@pytest.fixture(scope="module")
def doc():
    return load(WORKFLOW)


@pytest.fixture(scope="module")
def raw():
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_passes_every_check(doc, raw):
    assert violations(doc, raw) == []


def test_the_triggers_are_exactly_the_six_that_are_listed(doc):
    assert set(doc["on"]) == {"release", "issues", "discussion", "discussion_comment", "push", "workflow_dispatch"}
    assert doc["on"]["release"]["types"] == ["released"]
    assert doc["on"]["issues"]["types"] == ["opened", "labeled"]
    assert doc["on"]["discussion"]["types"] == ["created"]
    assert doc["on"]["discussion_comment"]["types"] == ["created"]


def test_no_trigger_can_run_code_from_a_fork_or_reach_a_secret_from_one(doc):
    for forbidden in (
        "pull_request",
        "pull_request_target",
        "workflow_run",
        "repository_dispatch",
        "schedule",
        "issue_comment",
    ):
        assert forbidden not in doc["on"]


def test_the_poster_gets_exactly_the_three_secrets_and_the_token(doc):
    steps = doc["jobs"]["relay"]["steps"]
    post = [s for s in steps if "run" in s][0]
    assert set(post["env"]) == WEBHOOK_SECRETS | {"GITHUB_TOKEN"}
    assert post["run"].strip().startswith("python3 discord/relay/post.py --layout discord/layout/")


def test_the_files_the_workflow_runs_exist_and_the_guard_names_the_layout_repository(doc):
    command = [s for s in doc["jobs"]["relay"]["steps"] if "run" in s][0]["run"].split()
    assert (MONOREPO / command[1]).is_file()
    layout = MONOREPO / command[-1]
    assert layout.is_file()
    guard = re.search(r"== '([^']+)'", doc["jobs"]["relay"]["if"]).group(1)
    assert tomllib.loads(layout.read_text(encoding="utf-8"))["relay"]["repository"] == guard


def test_the_ci_alert_job_is_last_runs_only_on_main_and_holds_one_secret():
    ci = load(MONOREPO / ".github" / "workflows" / "ci.yml")
    job = ci["jobs"]["ci-alert"]
    assert list(ci["jobs"])[-1] == "ci-alert"
    assert "failure()" in job["if"] and "refs/heads/main" in job["if"] and "push" in job["if"]
    assert "--ci-failure" in "\n".join(step["run"] for step in job["steps"] if "run" in step)
    secrets = {k for step in job["steps"] for k, v in (step.get("env") or {}).items() if "secrets." in str(v)}
    assert secrets == {"DISCORD_WEBHOOK_CI_ALERTS"}


def test_the_workflow_stays_at_the_root_of_the_monorepo_and_not_in_a_published_folder():
    assert WORKFLOW.parent == MONOREPO / ".github" / "workflows"
    assert ROOT not in WORKFLOW.parents


def test_ci_runs_the_discord_job_with_no_secret():
    ci = load(MONOREPO / ".github" / "workflows" / "ci.yml")
    job = ci["jobs"]["discord"]
    # a job may state its own permissions or inherit the workflow's, which is read-only for contents
    assert job.get("permissions") == {"contents": "read"}, "state the permission on the job itself, never inherit it"
    text = (MONOREPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = text[text.index("  discord:") : text.index("  firmware:")]
    assert "secrets." not in block
    for step in job["steps"]:
        if "uses" in step:
            assert SHA_PIN.match(step["uses"])
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False, "no stored git credentials in CI"
    runs = "\n".join(step["run"] for step in job["steps"] if "run" in step)
    for wanted in (
        "ruff check",
        "pytest",
        "serverkit check",
        "export-content --check",
        "npm ci",
        "npm test",
        "npm run typecheck",
    ):
        assert wanted in runs


def test_dependabot_watches_the_discord_folders():
    updates = load(MONOREPO / ".github" / "dependabot.yml")["updates"]
    pairs = set()
    for update in updates:
        for directory in [update["directory"]] if "directory" in update else update["directories"]:
            pairs.add((update["package-ecosystem"], directory))
    assert ("pip", "/discord") in pairs and ("npm", "/discord/worker") in pairs
    assert ("github-actions", "/") in pairs


# ---------------------------------------------------------------- the checker catches each fault


def mutated(doc, change):
    copy_ = copy.deepcopy(doc)
    change(copy_)
    return copy_


def post_step(doc):
    return [s for s in doc["jobs"]["relay"]["steps"] if "run" in s][0]


@pytest.mark.parametrize(
    "change, fragment",
    [
        (lambda d: d["on"].update({"pull_request_target": {"types": ["opened"]}}), "does not list"),
        (lambda d: d["on"].update({"pull_request": {}}), "does not list"),
        (lambda d: d["on"].update({"workflow_run": {"workflows": ["CI"]}}), "does not list"),
        (lambda d: d["on"].update({"schedule": [{"cron": "0 * * * *"}]}), "does not list"),
        (lambda d: d["on"]["release"].update({"types": ["published"]}), "trigger release"),
        (lambda d: d["on"]["issues"].update({"types": ["opened", "edited"]}), "trigger issues"),
        (lambda d: d["on"]["issues"].update({"types": ["opened"]}), "trigger issues"),
        (lambda d: d["on"]["issues"].update({"types": ["opened", "labeled", "closed"]}), "trigger issues"),
        (
            lambda d: d["on"]["discussion_comment"].update({"types": ["created", "edited"]}),
            "trigger discussion_comment",
        ),
        (lambda d: d["on"].pop("discussion_comment"), "trigger discussion_comment"),
        (lambda d: d["on"].update({"issue_comment": {"types": ["created"]}}), "does not list"),
        (lambda d: d["on"].update({"discussion": {"types": ["created", "edited"]}}), "trigger discussion"),
        (lambda d: d["on"]["discussion"].update({"types": ["created", "edited"]}), "trigger discussion"),
        (lambda d: d["on"].update({"push": {"branches": ["main"], "tags": ["v*"]}}), "trigger push"),
        (lambda d: d.update({"permissions": {"contents": "read"}}), "workflow level permissions"),
        (
            lambda d: d["jobs"]["relay"].update({"permissions": {"contents": "write", "actions": "read"}}),
            "permissions are",
        ),
        (lambda d: d["jobs"]["relay"]["permissions"].update({"issues": "write"}), "permissions are"),
        (lambda d: d["jobs"]["relay"]["permissions"].pop("actions"), "permissions are"),
        (lambda d: d["jobs"]["relay"].update({"timeout-minutes": 30}), "time-out"),
        (lambda d: d["jobs"]["relay"].pop("timeout-minutes"), "time-out"),
        (lambda d: d["jobs"]["relay"].pop("concurrency"), "concurrency"),
        (lambda d: d["jobs"]["relay"]["concurrency"].update({"cancel-in-progress": True}), "never cancel"),
        (lambda d: d["jobs"]["relay"].pop("environment"), "environment"),
        (lambda d: d["jobs"]["relay"].pop("if"), "guard"),
        (lambda d: d["jobs"]["relay"]["steps"][0].update({"uses": "actions/checkout@v4"}), "not pinned"),
        (lambda d: d["jobs"]["relay"]["steps"][0].update({"uses": "actions/checkout@" + "a" * 39}), "not pinned"),
        (lambda d: d["jobs"]["relay"]["steps"][0]["with"].update({"persist-credentials": True}), "persist-credentials"),
        (lambda d: d["jobs"]["relay"]["steps"][0]["with"].update({"ref": "${{ github.head_ref }}"}), "main"),
        (
            lambda d: post_step(d).update({"run": "echo ${{ github.event.issue.title }}"}),
            "run line holds an expression",
        ),
        (
            lambda d: post_step(d).update({"run": "echo ${{ github.event.issue.number }}"}),
            "run line holds an expression",
        ),
        (
            lambda d: post_step(d).update({"run": 'echo "$GITHUB_EVENT_PATH" ${{ secrets.DISCORD_WEBHOOK_FEED }}'}),
            "run line holds an expression",
        ),
        (lambda d: post_step(d)["env"].update({"TITLE": "${{ github.event.issue.title }}"}), "safe list"),
        (lambda d: post_step(d)["env"].update({"BRANCH": "${{ github.head_ref }}"}), "safe list"),
        (lambda d: post_step(d)["env"].update({"BODY": "${{ github.event.discussion.body }}"}), "safe list"),
        (
            lambda d: d["jobs"]["relay"]["concurrency"].update({"group": "x-${{ github.event.release.name }}"}),
            "concurrency",
        ),
        (
            lambda d: d["jobs"]["relay"].update(
                {"env": {"DISCORD_WEBHOOK_FEED": "${{ secrets.DISCORD_WEBHOOK_FEED }}"}}
            ),
            "never to a job",
        ),
        (
            lambda d: d["jobs"]["relay"]["steps"][0].update(
                {"env": {"DISCORD_WEBHOOK_FEED": "${{ secrets.DISCORD_WEBHOOK_FEED }}"}}
            ),
            "not the poster",
        ),
        (
            lambda d: post_step(d)["env"].update({"EXTRA": "${{ secrets.DISCORD_WEBHOOK_FEED }}"}),
            "exactly the expected",
        ),
        (
            lambda d: d["on"].update(
                {"workflow_dispatch": {"inputs": {"dry_run": {"type": "boolean", "default": False}}}}
            ),
            "defaults to on",
        ),
        (lambda d: d["on"].update({"workflow_dispatch": {"inputs": {"title": {"type": "string"}}}}), "one input"),
    ],
)
def test_the_checker_catches_each_fault(doc, raw, change, fragment):
    problems = violations(mutated(doc, change), raw)
    assert any(fragment in problem for problem in problems), problems


def test_the_checker_catches_a_pin_with_no_version_comment(doc, raw):
    stripped = re.sub(r"(uses: \S+@[0-9a-f]{40}) # v\S+", r"\1", raw)
    assert any("no version comment" in p for p in violations(doc, stripped))


def test_the_checker_reads_a_hostile_workflow_written_out_in_full():
    hostile = parse(
        "on:\n"
        "  pull_request_target:\n"
        "    types: [opened]\n"
        "permissions:\n"
        "  contents: write\n"
        "jobs:\n"
        "  relay:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
        "      - run: echo '${{ github.event.pull_request.title }}'\n"
    )
    problems = violations(hostile, "")
    assert len(problems) >= 6


# ---------------------------------------------------------------- actionlint


def test_actionlint_accepts_the_workflow_and_ci():
    if shutil.which("actionlint") is None:
        skip_loudly("actionlint is not installed, so the workflow was not linted")
    result = subprocess.run(
        ["actionlint", str(WORKFLOW), str(MONOREPO / ".github" / "workflows" / "ci.yml")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
