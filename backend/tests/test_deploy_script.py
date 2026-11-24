"""
infra/scripts/deploy.sh and the files it relies on must keep the properties that were each added after a real fault:

1. on a database that exists, the migrations are applied BEFORE the new code serves a request
2. on a first deploy the tables are created by the application's own step and the migrations still run, once, afterwards
3. the safety checks are kept: a signed tag (verified, not a drifted checkout), the env file's mode, the password
   checks, every failing step stops the deploy and the API runs only as production, under the limited database login
4. the compose file keeps its hardening, the SQL keeps the role small and the Nginx check compares exact files

The release block and the stages after it are RUN, not read. The tests build a throwaway git repository signed with a
throwaway SSH key and put stand-ins for `docker` and `curl` first on the PATH, so a stage that is removed or made to
ignore a failure changes what the script does and a test fails. The remaining tests read the non-comment lines of the
files, because a property that is only mentioned in a comment is not a property. They check order and presence and not
the exact wording.

The test container mounts backend/ only, so the scripts are not there. These tests run from a checkout of the whole repo
(python -m pytest backend/tests/test_deploy_script.py) and in CI and skip where the files are absent.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_INFRA = _REPO / "infra"
_SCRIPTS = _INFRA / "scripts"

if not (_SCRIPTS / "deploy.sh").is_file():
    pytest.skip("infra/scripts/deploy.sh is not present in this environment", allow_module_level=True)

_NEEDS_TOOLS = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("git") and shutil.which("ssh-keygen") and shutil.which("python3")),
    reason="needs bash, git, ssh-keygen and python3 on the host to build a signed throwaway repository",
)


def _code(path: Path, comment: str = "#") -> str:
    """The file without its comment lines and without trailing comments that follow whitespace."""
    kept = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(comment):
            continue
        kept.append(re.sub(rf"\s+{re.escape(comment)}\s.*$", "", line))
    return "\n".join(kept)


DEPLOY = _code(_SCRIPTS / "deploy.sh")
LIB = _code(_SCRIPTS / "lib.sh")
MIGRATE = _code(_SCRIPTS / "migrate.sh")
DB_ROLE = _code(_SCRIPTS / "db-role.sh")
ROLE_SQL = _code(_INFRA / "sql" / "roles" / "app-role.sql", "--")
CHECK_SQL = _code(_INFRA / "sql" / "roles" / "app-role-check.sql", "--")
CHECK_NGINX = _code(_SCRIPTS / "check-nginx.sh")
RESTORE = _code(_SCRIPTS / "restore.sh")
BACKUP = _code(_SCRIPTS / "backup.sh")


# --------------------------------------------------------------------------------------------------------------------
# the stand-ins and the throwaway tree
# --------------------------------------------------------------------------------------------------------------------

_DOCKER_STUB = r'''#!/usr/bin/env python3
"""Stand-in for docker. Logs every call to $FAKE_LOG and answers what deploy.sh asks, driven by FAKE_* variables."""
import os, sys
args = sys.argv[1:]
log = open(os.environ["FAKE_LOG"], "a")
def note(text): log.write(text + "\n"); log.flush()
if args[:1] == ["image"]:
    note("image " + " ".join(args[1:])); sys.exit(0)
if args[:1] != ["compose"]:
    note("other " + " ".join(args)); sys.exit(0)
rest = args[1:]
i = rest.index("-f") + 2
sub = rest[i:]
verb = sub[0]
if verb == "up":
    note("up " + " ".join(sub[1:]))
    sys.exit(int(os.environ.get("FAKE_UP_EXIT", "0")))
if verb == "build":
    note("build"); sys.exit(0)
if verb == "run":
    note("run " + " ".join(sub[1:])); sys.exit(int(os.environ.get("FAKE_SCHEMA_EXIT", "0")))
if verb == "stop":
    note("stop " + " ".join(sub[1:])); sys.exit(0)
if verb == "exec":
    service = [a for a in sub[1:] if a in ("db", "backend")][0]
    if service == "backend":
        note("exec backend " + " ".join(sub[1:]))
        sys.exit(int(os.environ.get("FAKE_PRODUCTION_EXIT", "0")))
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    joined = " ".join(sub[1:])
    if "pg_dump" in joined:
        note("pg_dump")
        for _ in range(int(os.environ.get("FAKE_DUMP_LINES", "200"))):
            sys.stdout.write("INSERT INTO t VALUES ('" + os.urandom(24).hex() + "');\n")
        sys.exit(0)
    if "to_regclass('public.users')" in joined:
        note("lookup users"); print(os.environ.get("FAKE_USERS", "t")); sys.exit(0)
    if "to_regclass('public.devices')" in joined:
        note("lookup schema")
        if os.environ.get("FAKE_LOOKUP_FAIL"): sys.exit(1)
        print(os.environ.get("FAKE_SCHEMA_EXISTS", "f")); sys.exit(0)
    if "count(*) FROM public.schema_migrations" in joined:
        print(os.environ.get("FAKE_RECORD_COUNT", "0")); sys.exit(0)
    if "SELECT sha256 FROM public.schema_migrations WHERE filename" in joined:
        name = joined.split("filename = '")[1].split("'")[0]
        rec = dict(p.split("=", 1) for p in os.environ.get("FAKE_RECORDED", "").split(",") if p)
        print(rec.get(name, "")); sys.exit(0)
    if "CREATE TABLE IF NOT EXISTS public.schema_migrations" in joined:
        note("record table"); sys.exit(0)
    if "UPDATE public.schema_migrations SET sha256" in joined:
        note("rehash"); sys.exit(0)
    if "the application role is missing" in stdin:
        note("role check")
        sys.exit(int(os.environ.get("FAKE_CHECK_EXIT", "0")))
    if "CREATE ROLE" in stdin:
        note("role apply"); sys.exit(int(os.environ.get("FAKE_ROLE_EXIT", "0")))
    if "INSERT INTO public.schema_migrations" in stdin:
        name = stdin.split("VALUES ('")[1].split("'")[0]
        note("migration " + name)
        if os.environ.get("FAKE_FAIL_MIGRATION") == name: sys.exit(3)
        sys.exit(0)
    note("db other " + joined[:60]); sys.exit(0)
note("compose " + verb); sys.exit(0)
'''

_AGE_STUB = r'''#!/bin/sh
# stand-in for age: the real header line, then the input unchanged (the test reads sizes and names, not secrets)
printf 'age-encryption.org/v1\n'
cat
'''

_CURL_STUB = r'''#!/bin/sh
# stand-in for curl: the caller-address loop asks for the status code and everything else asks for the body
case "$*" in
    *http_code*) printf '%s' "${FAKE_TRUST_CODE:-200}" ;;
    *)
        if [ -n "${FAKE_STATUS_BODY:-}" ]; then
            printf '%s' "${FAKE_STATUS_BODY}"
        else
            printf '%s' '{"status":"operational","database":"ok","redis":"ok","model":"none"}'
        fi
        ;;
esac
'''


def _run(cmd, cwd, env=None, check=True, input_text=None):
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, input=input_text)
    if check and result.returncode != 0:
        raise AssertionError(f"{cmd} failed: {result.stdout}\n{result.stderr}")
    return result


class Tree:
    """A copy of the scripts in a throwaway git repository, with a throwaway release key."""

    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), ("age", _AGE_STUB)):
            target = self.bin / name
            target.write_text(body)
            target.chmod(target.stat().st_mode | stat.S_IEXEC)
        repo = root / "repo"
        self.repo = repo
        (repo / "infra").mkdir(parents=True)
        shutil.copytree(_SCRIPTS, repo / "infra" / "scripts")
        shutil.copytree(_INFRA / "sql", repo / "infra" / "sql")
        (repo / "infra" / "nginx").mkdir()
        shutil.copy(_INFRA / "nginx" / "api.phaemos.com.conf", repo / "infra" / "nginx")
        shutil.copy(_INFRA / "docker-compose.prod.yml", repo / "infra")
        (repo / "backend" / "migrations").mkdir(parents=True)
        for number, name in enumerate(("001_a.sql", "002_b.sql", "003_c.sql")):
            (repo / "backend" / "migrations" / name).write_text(f"-- migration {number}\nSELECT {number};\n")
        self.env_file = repo / "backend" / ".env"
        self.write_env()
        self.log = root / "calls.log"
        self.log.write_text("")
        self.key = root / "sign"
        self.other_key = root / "other"
        for key in (self.key, self.other_key):
            _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key), "-C", "t"], root)
        self.signers = root / "allowed_signers"
        self.signers.write_text(f'release@example.org namespaces="git" {self.key.with_suffix(".pub").read_text()}')
        self.git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
        }
        # the checkout's own env file is untracked and ignored, as on a real droplet
        (repo / ".gitignore").write_text("backend/.env\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "release")

    def write_env(self, **overrides):
        values = {
            "SECRET_KEY": "k" * 64, "POSTGRES_DB": "db", "POSTGRES_USER": "owner",
            "POSTGRES_PASSWORD": "a" * 24, "POSTGRES_APP_USER": "app", "POSTGRES_APP_PASSWORD": "b" * 24,
            "REDIS_PASSWORD": "c" * 24,
            "ALLOWED_ORIGINS": "https://dashboard.example.org,https://example.org",
        }
        values.update(overrides)
        self.env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items() if v is not None))
        self.env_file.chmod(0o600)

    def git(self, *args, check=True):
        return _run(["git", *args], self.repo, self.git_env, check)

    def tag(self, name, signer=None, signed=True):
        if not signed:
            self.git("tag", name)
            return
        key = (signer or self.key).with_suffix(".pub")
        self.git("-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "tag", "-s", "-m", name, name)

    def run(self, extra_env=None, args=()):
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "FAKE_LOG": str(self.log),
            "DEPLOY_ALLOWED_SIGNERS": str(self.signers),
            "STATUS_URL": "http://127.0.0.1:1/status",
            "NGINX_DUMP_FILE": str(self.root / "nginx-dump"),
            "NGINX_SITE_AVAILABLE": str(self.root / "available.conf"),
            "NGINX_SITE_ENABLED": str(self.root / "enabled.conf"),
            "NGINX_CORS_FILE": str(self.root / "cors.conf"),
        }
        for name in ("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "POSTGRES_USER"):
            env.pop(name, None)
        env.update(extra_env or {})
        self.log.write_text("")
        return _run(["bash", str(self.repo / "infra" / "scripts" / "deploy.sh"), *args], self.repo, env, check=False)

    def install_good_nginx(self):
        site = (self.repo / "infra" / "nginx" / "api.phaemos.com.conf").read_text()
        cors = _run(["bash", str(self.repo / "infra" / "scripts" / "render-cors.sh")], self.repo, {**os.environ}).stdout
        (self.root / "available.conf").write_text(site)
        (self.root / "enabled.conf").write_text(site)
        (self.root / "cors.conf").write_text(cors)
        (self.root / "nginx-dump").write_text(
            f"# configuration file {self.root / 'enabled.conf'}:\n{site}\n# configuration file {self.root / 'cors.conf'}:\n{cors}\n"
        )

    def calls(self):
        return self.log.read_text().splitlines()


@pytest.fixture()
def tree(tmp_path):
    if not (shutil.which("bash") and shutil.which("git") and shutil.which("ssh-keygen") and shutil.which("python3")):
        pytest.skip("needs bash, git, ssh-keygen and python3 on the host")
    t = Tree(tmp_path)
    t.install_good_nginx()
    return t


def _first(calls, prefix, start=0):
    for index in range(start, len(calls)):
        if calls[index].startswith(prefix):
            return index
    raise AssertionError(f"no call starting {prefix!r} in {calls}")


def _last(calls, prefix):
    for index in range(len(calls) - 1, -1, -1):
        if calls[index].startswith(prefix):
            return index
    raise AssertionError(f"no call starting {prefix!r} in {calls}")


def _signed_release(tree):
    tree.tag("v1.0.0")
    return tree


# --------------------------------------------------------------------------------------------------------------------
# 1 and 2: the order of the schema step (the old test's two properties, now by running the script)
# --------------------------------------------------------------------------------------------------------------------

@_NEEDS_TOOLS
def test_on_an_existing_database_the_migrations_are_applied_before_the_new_code_starts(tree):
    _signed_release(tree)
    result = tree.run({"FAKE_SCHEMA_EXISTS": "t"})
    assert result.returncode == 0, result.stderr + result.stdout
    calls = tree.calls()
    database = _first(calls, "up -d --wait --wait-timeout 120 db")
    role = _first(calls, "role apply")
    migrations = [i for i, c in enumerate(calls) if c.startswith("migration ")]
    schema_job = _first(calls, "run ")
    api_start = _last(calls, "up -d --wait")
    assert database < role < min(migrations) <= max(migrations) < schema_job < api_start
    assert [calls[i] for i in migrations] == ["migration 001_a.sql", "migration 002_b.sql", "migration 003_c.sql"]


@_NEEDS_TOOLS
def test_a_first_deploy_creates_the_tables_then_migrates_once_and_all_before_the_api_starts(tree):
    _signed_release(tree)
    result = tree.run({"FAKE_SCHEMA_EXISTS": "f"})
    assert result.returncode == 0, result.stderr + result.stdout
    calls = tree.calls()
    schema_job = _first(calls, "run ")
    migrations = [i for i, c in enumerate(calls) if c.startswith("migration ")]
    api_start = _last(calls, "up -d --wait")
    assert len(migrations) == 3, "each file runs exactly once"
    assert schema_job < min(migrations) and max(migrations) < api_start


@_NEEDS_TOOLS
def test_every_compose_start_waits_for_health(tree):
    _signed_release(tree)
    tree.run({"FAKE_SCHEMA_EXISTS": "t"})
    ups = [c for c in tree.calls() if c.startswith("up ")]
    assert ups and all("--wait" in c.split() for c in ups), ups


# --------------------------------------------------------------------------------------------------------------------
# 3: the release block
# --------------------------------------------------------------------------------------------------------------------

@_NEEDS_TOOLS
def test_a_signed_tag_passes_and_the_tag_and_commit_are_printed(tree):
    _signed_release(tree)
    result = tree.run()
    assert result.returncode == 0, result.stderr + result.stdout
    commit = tree.git("rev-parse", "HEAD").stdout.strip()
    assert f"deployed: v1.0.0 at commit {commit}" in result.stdout


@_NEEDS_TOOLS
def test_head_without_a_tag_is_refused_and_nothing_is_started(tree):
    result = tree.run()
    assert result.returncode != 0 and "not at a tag" in result.stderr
    assert tree.calls() == []


@_NEEDS_TOOLS
def test_a_tag_signed_by_a_key_that_is_not_listed_is_refused(tree):
    tree.tag("v1.0.0", signer=tree.other_key)
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_a_lightweight_tag_is_refused(tree):
    tree.tag("v1.0.0", signed=False)
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_a_changed_tracked_file_is_refused(tree):
    _signed_release(tree)
    (tree.repo / "infra" / "scripts" / "backup.sh").write_text("# changed\n")
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_an_untracked_migration_is_refused(tree):
    _signed_release(tree)
    (tree.repo / "backend" / "migrations" / "999_x.sql").write_text("SELECT 1;\n")
    result = tree.run()
    assert result.returncode != 0 and "untracked" in result.stderr and tree.calls() == []


@_NEEDS_TOOLS
def test_an_ignored_file_where_the_migrations_look_is_refused(tree):
    _signed_release(tree)
    (tree.repo / ".gitignore").write_text("backend/.env\nbackend/migrations/999_y.sql\n")
    tree.git("add", ".gitignore")
    tree.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "more ignore")
    tree.tag("v1.0.1")
    (tree.repo / "backend" / "migrations" / "999_y.sql").write_text("SELECT 1;\n")
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_an_old_signed_tag_filed_under_a_new_name_is_refused(tree):
    _signed_release(tree)
    old_object = tree.git("rev-parse", "refs/tags/v1.0.0").stdout.strip()
    tree.git("update-ref", "refs/tags/v9.9.9", old_object)
    tree.git("tag", "-d", "v1.0.0")
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_the_first_install_override_skips_only_the_signature_and_is_refused_once_a_schema_exists(tree):
    # no tag at all and the override accepts it on an empty database
    result = tree.run({"DEPLOY_FIRST_INSTALL": "yes", "FAKE_SCHEMA_EXISTS": "f"})
    assert result.returncode == 0 and "unsigned first install" in result.stdout, result.stderr
    # the same override on a database that already holds the application's tables
    result = tree.run({"DEPLOY_FIRST_INSTALL": "yes", "FAKE_SCHEMA_EXISTS": "t"})
    assert result.returncode != 0 and "refused" in result.stderr
    assert not [c for c in tree.calls() if c.startswith(("build", "run ", "migration"))]


@_NEEDS_TOOLS
def test_the_override_does_not_skip_the_nginx_check_and_the_nginx_switch_does_not_skip_the_signature(tree):
    (tree.root / "nginx-dump").write_text("")
    result = tree.run({"DEPLOY_FIRST_INSTALL": "yes"})
    assert result.returncode != 0, "the first-install override must not skip the Nginx check"
    result = tree.run({"DEPLOY_SKIP_NGINX_CHECK": "yes"})
    assert result.returncode != 0 and "not at a tag" in result.stderr, "the Nginx switch must not skip the signature"
    result = tree.run({"DEPLOY_FIRST_INSTALL": "yes", "DEPLOY_SKIP_NGINX_CHECK": "yes"})
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------------------------------------------------
# the pre-flight checks and every step that must stop the deploy
# --------------------------------------------------------------------------------------------------------------------

@_NEEDS_TOOLS
@pytest.mark.parametrize(
    "overrides",
    [
        {"SECRET_KEY": "short"},
        {"POSTGRES_PASSWORD": "short"},
        {"POSTGRES_PASSWORD": "a" * 23},
        {"POSTGRES_APP_PASSWORD": "short"},
        {"POSTGRES_APP_PASSWORD": "a" * 24},  # the same as the owner's
        {"REDIS_PASSWORD": "short"},
        {"POSTGRES_APP_USER": "owner"},  # the API must not sign in as the owner
        {"POSTGRES_DB": None},
        {"POSTGRES_APP_USER": None},
    ],
)
def test_the_pre_flight_checks_stop_the_deploy_before_anything_starts(tree, overrides):
    _signed_release(tree)
    tree.write_env(**overrides)
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == [], result.stdout + result.stderr


@_NEEDS_TOOLS
def test_an_env_file_that_other_users_can_read_is_refused(tree):
    _signed_release(tree)
    tree.env_file.chmod(0o644)
    result = tree.run()
    assert result.returncode != 0 and tree.calls() == []


@_NEEDS_TOOLS
def test_a_secret_set_in_the_shell_is_refused(tree):
    _signed_release(tree)
    result = tree.run({"SECRET_KEY": "x" * 64})
    assert result.returncode != 0 and "shell" in result.stderr and tree.calls() == []


@_NEEDS_TOOLS
@pytest.mark.parametrize(
    "env,expected",
    [
        ({"FAKE_LOOKUP_FAIL": "1"}, "could not ask"),
        ({"FAKE_ROLE_EXIT": "3"}, None),
        ({"FAKE_SCHEMA_EXIT": "1"}, None),
        ({"FAKE_FAIL_MIGRATION": "002_b.sql"}, None),
        ({"FAKE_CHECK_EXIT": "3"}, None),
        ({"FAKE_PRODUCTION_EXIT": "1"}, "production"),
        ({"FAKE_TRUST_CODE": "429"}, "different callers"),
        ({"FAKE_STATUS_BODY": '{"status":"degraded"}'}, "operational"),
        ({"FAKE_STATUS_BODY": '{"status":"operational","model":"error"}'}, "model"),
    ],
)
def test_a_failing_step_stops_the_deploy_and_what_follows_does_not_run(tree, env, expected):
    _signed_release(tree)
    result = tree.run({"FAKE_SCHEMA_EXISTS": "t", **env})
    assert result.returncode != 0, result.stdout
    if expected:
        assert expected in result.stderr
    assert "deployed:" not in result.stdout
    calls = tree.calls()
    if "FAKE_FAIL_MIGRATION" in env:
        assert not [c for c in calls if c.startswith("migration 003")], "a failed migration must stop the next one"
        assert not [c for c in calls if c.startswith("up -d --wait --wait-timeout 240")], "the API must not start"
    if "FAKE_ROLE_EXIT" in env or "FAKE_LOOKUP_FAIL" in env:
        assert not [c for c in calls if c.startswith("build")]


@_NEEDS_TOOLS
def test_the_status_of_the_api_is_waited_for_and_asked_of_the_container_for_production(tree):
    _signed_release(tree)
    result = tree.run()
    assert result.returncode == 0
    assert any(c.startswith("exec backend") and "is_development" in c for c in tree.calls())


@_NEEDS_TOOLS
def test_the_role_is_made_before_any_schema_work_and_checked_after_the_api_starts(tree):
    _signed_release(tree)
    tree.run()
    calls = tree.calls()
    assert _first(calls, "role apply") < _first(calls, "build") < _last(calls, "up -d --wait")
    assert _last(calls, "up -d --wait") < _first(calls, "role check")


# --------------------------------------------------------------------------------------------------------------------
# nginx: the exact comparison
# --------------------------------------------------------------------------------------------------------------------

def _mutate_nginx(tree, old, new):
    site = (tree.repo / "infra" / "nginx" / "api.phaemos.com.conf").read_text()
    assert old in site, old
    mutated = site.replace(old, new, 1)
    (tree.root / "available.conf").write_text(mutated)
    (tree.root / "enabled.conf").write_text(mutated)
    cors = (tree.root / "cors.conf").read_text()
    (tree.root / "nginx-dump").write_text(
        f"# configuration file {tree.root / 'enabled.conf'}:\n{mutated}\n# configuration file {tree.root / 'cors.conf'}:\n{cors}\n"
    )


@_NEEDS_TOOLS
@pytest.mark.parametrize(
    "old,new",
    [
        ("limit_req zone=phaemos_api burst=40 nodelay;", ""),
        ("limit_conn api_per_addr 100;", ""),
        ("rate=30r/m", "rate=30000r/s"),
        ("proxy_set_header X-Real-IP $remote_addr;", ""),
        ("location = /metrics {\n        return 404;\n    }", ""),
        ("client_max_body_size 3m;", "client_max_body_size 3000m;"),
        ("ssl_protocols TLSv1.2 TLSv1.3;", "ssl_protocols TLSv1 TLSv1.2 TLSv1.3;"),
        ("client_body_timeout 10s;", "client_body_timeout 86400s;"),
        ("client_max_body_size 600000;", "client_max_body_size 64k;"),
        ("error_page 429 @rate_limited;", ""),
        ("error_page 413 @payload_too_large;", ""),
        ("error_page 502 @upstream_unavailable;", ""),
        ("error_page 504 @upstream_timeout;", ""),
        ("add_header Access-Control-Allow-Origin $phaemos_cors_origin always;", "add_header Access-Control-Allow-Origin * always;"),
        ('add_header Retry-After "2" always;', ""),
        ("~^/api/v1/contact/?$", "~^/api/v1/contactus/?$"),
    ],
)
def test_any_change_to_the_installed_nginx_site_stops_the_deploy(tree, old, new):
    _signed_release(tree)
    _mutate_nginx(tree, old, new)
    result = tree.run()
    assert result.returncode != 0, "a changed site file must fail the Nginx check"
    assert "WRONG in the Nginx set-up" in result.stderr


@_NEEDS_TOOLS
def test_the_site_that_nginx_loaded_must_match_even_when_the_installed_file_does(tree):
    _signed_release(tree)
    site = (tree.repo / "infra" / "nginx" / "api.phaemos.com.conf").read_text()
    cors = (tree.root / "cors.conf").read_text()
    (tree.root / "nginx-dump").write_text(
        f"# configuration file {tree.root / 'enabled.conf'}:\n{site.replace('64k', '64000k')}\n# configuration file {tree.root / 'cors.conf'}:\n{cors}\n"
    )
    result = tree.run()
    assert result.returncode != 0


# --------------------------------------------------------------------------------------------------------------------
# migrate.sh: once each, recorded, refuses a changed file
# --------------------------------------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


@_NEEDS_TOOLS
def test_migrate_applies_only_files_that_were_not_applied_and_refuses_a_changed_one(tree):
    migrations = tree.repo / "backend" / "migrations"

    def migrate(recorded, *args):
        env = {
            **os.environ, "PATH": f"{tree.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(tree.log),
            "FAKE_RECORDED": ",".join(f"{name}={digest}" for name, digest in recorded.items()),
            "FAKE_RECORD_COUNT": str(len(recorded)),
        }
        for name in ("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "POSTGRES_USER"):
            env.pop(name, None)
        tree.log.write_text("")
        return _run(["bash", str(tree.repo / "infra" / "scripts" / "migrate.sh"), *args], tree.repo, env, check=False)

    result = migrate({})
    assert result.returncode == 0 and [c for c in tree.calls() if c.startswith("migration")] == [
        "migration 001_a.sql", "migration 002_b.sql", "migration 003_c.sql"]
    # the first two recorded and unchanged: only the third runs
    done = {n: _sha(migrations / n) for n in ("001_a.sql", "002_b.sql")}
    result = migrate(done)
    assert result.returncode == 0 and [c for c in tree.calls() if c.startswith("migration")] == ["migration 003_c.sql"]
    # a recorded file that has changed since: refused, loudly and nothing after it runs
    changed = {**done, "001_a.sql": "0" * 64}
    result = migrate(changed)
    assert result.returncode != 0 and "REFUSED" in result.stderr
    assert not [c for c in tree.calls() if c.startswith("migration")]
    # --rehash records the new hash and runs nothing
    result = migrate(changed, "--rehash", "001_a.sql")
    assert result.returncode == 0 and "rehash" in tree.calls() and not [c for c in tree.calls() if c.startswith("migration")]


# --------------------------------------------------------------------------------------------------------------------
# non-comment lines: the properties that can only be read
# --------------------------------------------------------------------------------------------------------------------

def test_the_scripts_stop_on_error_in_code_and_not_only_in_a_comment():
    for name, code in (("deploy.sh", DEPLOY), ("migrate.sh", MIGRATE), ("db-role.sh", DB_ROLE), ("restore.sh", RESTORE), ("backup.sh", BACKUP)):
        assert re.search(r"^set -euo pipefail$", code, re.MULTILINE), name


def test_every_psql_call_stops_on_the_first_error():
    assert "-v ON_ERROR_STOP=1" in LIB and "-v ON_ERROR_STOP=1" in MIGRATE
    for name, code in (("app-role.sql", ROLE_SQL), ("app-role-check.sql", CHECK_SQL)):
        assert re.search(r"^\\set ON_ERROR_STOP on$", code, re.MULTILINE), name
    for path in _SCRIPTS.glob("*.sh"):
        for number, line in enumerate(_code(path).splitlines(), 1):
            if re.search(r"\bpsql\b", line) and "ON_ERROR_STOP" not in line and "docker" not in line.split("psql")[0]:
                raise AssertionError(f"{path.name}: psql without ON_ERROR_STOP: {line.strip()}")


def test_the_migrations_are_applied_one_file_at_a_time_never_in_one_transaction_and_recorded_after_success():
    assert "--single-transaction" not in MIGRATE and "--single-transaction" not in DEPLOY
    assert re.search(r"for path in [^\n]*\*\.sql", MIGRATE)
    # the record is written in the same session, after the file
    assert MIGRATE.index('cat "${path}"') < MIGRATE.index("INSERT INTO public.schema_migrations")
    assert "REFUSED" in MIGRATE and "exit 1" in MIGRATE


def test_the_role_is_never_a_superuser_and_is_rebuilt_from_nothing_every_time():
    assert not re.search(r"(?<!NO)SUPERUSER", ROLE_SQL), "the role must never be made a superuser"
    assert "NOSUPERUSER" in ROLE_SQL and "NOCREATEROLE" in ROLE_SQL and "NOBYPASSRLS" in ROLE_SQL
    assert not re.search(r"GRANT\s+ALL", ROLE_SQL, re.IGNORECASE), "no GRANT ALL"
    for needle in ("REVOKE %I FROM %I", "REASSIGN OWNED BY", "DROP OWNED BY", "ALTER ROLE %I RESET ALL",
                   "ALTER ROLE %I IN DATABASE %I RESET ALL", "pg_auth_members", "lo_from_bytea",
                   "REVOKE CREATE ON SCHEMA public"):
        assert needle in ROLE_SQL, needle
    assert ROLE_SQL.index("BEGIN;") < ROLE_SQL.index("DROP OWNED BY") < ROLE_SQL.index("GRANT SELECT, INSERT, UPDATE, DELETE") < ROLE_SQL.index("COMMIT;")


def test_the_role_check_fails_on_every_left_over_power():
    # each guard raises its own error, so each must still be there and be a real error and not a no-op
    guards = (
        "the application role is missing or holds a dangerous attribute",
        "the application role is a member of another role",
        "another role can sign in or is a superuser besides the owner and the application role",
        "a table in the public schema lacks rights for the application role",
        "the application role may touch the record of applied migrations",
        "the application role holds a table right beyond select, insert, update and delete",
        "the application role holds a sequence right beyond usage and select",
        "the application role may create in the database or make temporary tables",
        "the application role may create objects in a schema",
        "the application role holds a database right beyond connect",
        "the application role owns an object, which it must not",
        "the application role has a default privilege beyond the four",
        "the application role carries saved settings",
        "the application role carries saved settings for a database",
        "the application role may create a large object",
    )
    for guard in guards:
        assert f"RAISE EXCEPTION '{guard}'" in CHECK_SQL, guard
    for needle in ("pg_auth_members", "pg_shdepend", "rolconfig", "pg_db_role_setting", "aclexplode", "rolsuper",
                   "rolcanlogin", "lo_from_bytea", "schema_migrations"):
        assert needle in CHECK_SQL, needle


def test_the_database_log_keeps_values_out():
    compose = (_INFRA / "docker-compose.prod.yml").read_text()
    for needle in ("log_min_error_statement=panic", "log_error_verbosity=terse", "log_statement=none"):
        assert needle in compose, needle


def test_the_restore_commits_only_after_the_whole_dump_and_rolls_back_on_a_signal():
    assert "BEGIN;" in RESTORE and "COMMIT;" in RESTORE and "ROLLBACK;" in RESTORE
    assert "--single-transaction" not in RESTORE
    assert re.search(r"trap on_signal INT TERM HUP", RESTORE)
    assert "lo_unlink" in RESTORE
    # the commit decision is made at the end of the stream and the stream goes through it
    assert re.search(r"dump_stream\n\} \| with_commit_decision \| db_psql", RESTORE)


def _backup(tree, extra_env=None, recipient=True):
    tree.write_env(**({"BACKUP_AGE_RECIPIENT": "age1" + "q" * 58} if recipient else {}))
    backups = tree.root / "backups"
    backups.mkdir(exist_ok=True)
    env = {
        **os.environ, "PATH": f"{tree.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(tree.log),
        "BACKUP_DIR": str(backups), "HOME": str(tree.root),
    }
    for name in ("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "POSTGRES_USER", "BACKUP_AGE_RECIPIENT"):
        env.pop(name, None)
    env.update(extra_env or {})
    result = _run(["bash", str(tree.repo / "infra" / "scripts" / "backup.sh")], tree.repo, env, check=False)
    return result, backups


@_NEEDS_TOOLS
def test_the_backup_is_encrypted_and_refuses_to_run_without_a_recipient(tree):
    result, backups = _backup(tree, recipient=False)
    assert result.returncode != 0
    assert not list(backups.glob("phaemos-*"))
    result, backups = _backup(tree)
    assert result.returncode == 0, result.stderr + result.stdout
    written = list(backups.glob("phaemos-*.sql.gz.age"))
    assert len(written) == 1 and written[0].read_bytes().startswith(b"age-encryption.org/v1")
    assert not list(backups.glob("phaemos-*.sql.gz")), "no plain file may be written"


@_NEEDS_TOOLS
def test_an_empty_database_is_not_backed_up_and_nothing_is_rotated(tree):
    backups = tree.root / "backups"
    backups.mkdir()
    for day in range(1, 8):
        (backups / f"phaemos-2026-01-0{day}_000000.sql.gz.age").write_bytes(b"age-encryption.org/v1\n" + b"x" * 4000)
    result, backups = _backup(tree, {"FAKE_USERS": "f"})
    assert result.returncode != 0
    assert len(list(backups.glob("phaemos-*.age"))) == 7, "no good backup may be removed"
    assert (backups / "BACKUP_FAILED").exists(), "a failure must leave a marker that a monitor can see"


@_NEEDS_TOOLS
def test_a_backup_less_than_half_the_size_of_the_newest_is_refused_before_anything_is_rotated(tree):
    backups = tree.root / "backups"
    backups.mkdir()
    for day in range(1, 8):
        (backups / f"phaemos-2026-01-0{day}_000000.sql.gz.age").write_bytes(b"age-encryption.org/v1\n" + b"x" * 100000)
    result, backups = _backup(tree, {"FAKE_DUMP_LINES": "400"})
    assert result.returncode != 0
    assert len(list(backups.glob("phaemos-*.age"))) == 7 and not list(backups.glob("*.partial"))


@_NEEDS_TOOLS
def test_rotation_keeps_seven_and_never_removes_the_file_just_written(tree):
    backups = tree.root / "backups"
    backups.mkdir()
    # seven files that sort AFTER any date written today, as a clock that went backwards would give
    for day in range(1, 8):
        (backups / f"phaemos-2099-01-0{day}_000000.sql.gz.age").write_bytes(b"age-encryption.org/v1\n" + b"x" * 3000)
    result, backups = _backup(tree, {"FAKE_DUMP_LINES": "400"})
    assert result.returncode == 0, result.stderr + result.stdout
    names = sorted(p.name for p in backups.glob("phaemos-*.age"))
    assert len(names) == 7
    assert any(not n.startswith("phaemos-2099") for n in names), "the new file was rotated away"


def test_the_backup_code_refuses_unencrypted_output():
    assert "refusing to write an unencrypted backup" in BACKUP and re.search(r"age -r", BACKUP)
    assert not re.search(r"\|\s*gzip[^|\n]*>\s*\"\$\{partial\}\"", BACKUP), "a dump must go through age"


def test_the_nginx_check_compares_exact_files_and_is_called_by_the_deploy():
    assert "cmp -s" in CHECK_NGINX and CHECK_NGINX.count("cmp -s") >= 2
    assert 'check-nginx.sh' in DEPLOY


# --------------------------------------------------------------------------------------------------------------------
# the compose file, parsed
# --------------------------------------------------------------------------------------------------------------------

def _compose():
    path = _INFRA / "docker-compose.prod.yml"
    try:
        import yaml

        # compose fills ${VAR} from the environment before it reads the file. The same stand-in values are put in
        # here so both ways of reading the file give the same result
        values = {
            "POSTGRES_DB": "d", "POSTGRES_USER": "o", "POSTGRES_PASSWORD": "p", "POSTGRES_APP_USER": "a",
            "POSTGRES_APP_PASSWORD": "q", "REDIS_PASSWORD": "r", "SECRET_KEY": "s",
        }
        text = re.sub(r"\$\{(\w+)(?::?[-?+][^}]*)?\}", lambda m: values.get(m.group(1), ""), path.read_text())
        return yaml.safe_load(text.replace("$$", "$"))
    except ImportError:
        pass
    if not shutil.which("docker"):
        pytest.skip("needs PyYAML or docker compose to read the compose file")
    import tempfile

    env = {
        **os.environ,
        "POSTGRES_DB": "d", "POSTGRES_USER": "o", "POSTGRES_PASSWORD": "p", "POSTGRES_APP_USER": "a",
        "POSTGRES_APP_PASSWORD": "q", "REDIS_PASSWORD": "r", "SECRET_KEY": "s",
    }
    # the file names ../backend/.env, so a copy sits in a folder that has an empty one
    with tempfile.TemporaryDirectory() as work:
        (Path(work) / "infra").mkdir()
        (Path(work) / "backend").mkdir()
        (Path(work) / "backend" / ".env").write_text("")
        copy = Path(work) / "infra" / "docker-compose.prod.yml"
        copy.write_text(path.read_text())
        out = subprocess.run(
            ["docker", "compose", "-f", str(copy), "config", "--format", "json"],
            capture_output=True, text=True, env=env,
        )
    if out.returncode != 0:
        pytest.skip(f"docker compose could not read the file: {out.stderr[:200]}")
    return json.loads(out.stdout)


def test_every_production_service_is_hardened():
    services = _compose()["services"]
    assert set(services) >= {"db", "redis", "backend", "schema"}
    for name, service in services.items():
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert service.get("read_only") is True, name
        assert service.get("pids_limit"), name
        assert service.get("mem_limit") or service.get("deploy"), name
        assert service.get("cpus"), name
        assert not service.get("cap_add"), name
        assert not service.get("privileged"), name


def test_the_api_is_published_on_the_loopback_address_only_and_the_data_services_are_not_published():
    services = _compose()["services"]
    for port in services["backend"]["ports"]:
        text = port if isinstance(port, str) else f"{port.get('host_ip', '')}:{port.get('published')}"
        assert text.startswith("127.0.0.1:"), text
    for name in ("db", "redis", "schema"):
        assert not services[name].get("ports"), name


def test_the_api_signs_in_as_the_limited_role_and_never_holds_the_owner_password():
    env = _compose()["services"]["backend"]["environment"]
    url = env["DATABASE_URL"] if isinstance(env, dict) else dict(e.split("=", 1) for e in env)["DATABASE_URL"]
    assert "POSTGRES_APP_USER" in (_INFRA / "docker-compose.prod.yml").read_text()
    assert "@db:5432" in url
    # the stand-in values are a (login) and q (password) for the API and o and p for the owner
    assert url.startswith("postgresql://a:q@db:5432/"), "the API must sign in as POSTGRES_APP_USER"
    if isinstance(env, dict):
        assert env.get("POSTGRES_PASSWORD") in ("", None)
        assert env.get("ENVIRONMENT") == "production"
    # the owner's login is in the schema job's URL and not in the API's
    raw = (_INFRA / "docker-compose.prod.yml").read_text()
    backend_block = raw[raw.index("\n  backend:"): raw.index("\n# two networks")]
    assert "${POSTGRES_USER}:${POSTGRES_PASSWORD}@db" not in backend_block


def test_the_data_services_are_on_a_network_with_no_route_out_and_the_images_are_pinned():
    compose = _compose()
    assert compose["networks"]["data"].get("internal") is True
    assert "data" in (compose["services"]["db"]["networks"] if isinstance(compose["services"]["db"]["networks"], list) else compose["services"]["db"]["networks"].keys())
    for name in ("db", "redis"):
        assert "@sha256:" in compose["services"][name]["image"], name
    assert re.search(r"^FROM python:[^@\n]+@sha256:[0-9a-f]{64}$", (_REPO / "backend" / "Dockerfile").read_text(), re.MULTILINE)


def test_redis_has_no_default_user_and_the_api_user_cannot_run_admin_commands():
    raw = (_INFRA / "docker-compose.prod.yml").read_text()
    assert "user default off" in raw and "-@admin" in raw and "-@dangerous" in raw


# --------------------------------------------------------------------------------------------------------------------
# the request classes, the JSON error answers and the origins file
# --------------------------------------------------------------------------------------------------------------------

_SITE = (_INFRA / "nginx" / "api.phaemos.com.conf").read_text()


def _class_of(path: str) -> str:
    """The class Nginx gives a path: the first regular expression of the map that matches, else the default."""
    block = re.search(r"^map \$uri \$phaemos_class \{(.*?)^\}", _SITE, re.MULTILINE | re.DOTALL).group(1)
    for line in block.splitlines():
        match = re.match(r"\s*~(\S+)\s+(\w+);", line)
        if match and re.search(match.group(1), path):
            return match.group(2)
    return re.search(r"default\s+(\w+);", block).group(1)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh", "/api/v1/auth/2fa/verify",
        "/api/v1/auth/accept-invite", "/api/v1/auth/invite/check", "/api/v1/auth/reset-password",
        "/api/v1/auth/google", "/api/v1/auth/google/callback", "/api/v1/auth/github", "/api/v1/auth/github/callback",
        "/api/v1/auth/microsoft", "/api/v1/auth/microsoft/callback", "/api/v1/auth/apple", "/api/v1/contact",
    ],
)
def test_the_routes_a_stranger_can_use_to_guess_or_flood_are_in_the_tight_class(path):
    assert _class_of(path) == "auth"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users", "/api/v1/users/abc/role", "/api/v1/invitations", "/api/v1/service-accounts", "/api/v1/tokens",
        "/api/v1/tokens/current", "/api/v1/auth/users", "/api/v1/auth/invite", "/api/v1/auth/tokens", "/api/v1/auth/me",
        "/api/v1/auth/logout", "/api/v1/auth/sessions", "/api/v1/auth/2fa/enable", "/api/v1/auth/change-password",
        "/api/v1/auth/providers", "/api/v1/devices", "/api/v1/telemetry/abc",
    ],
)
def test_signed_in_administration_and_its_deprecated_aliases_are_in_the_general_class(path):
    assert _class_of(path) == "api"


@pytest.mark.parametrize("path", ["/api/v1/telemetry", "/api/v1/telemetry/", "/api/v1/telemetry/batch"])
def test_single_and_batch_ingest_are_in_the_ingest_class(path):
    assert _class_of(path) == "ingest"


def test_only_the_batch_route_has_the_large_body_limit_and_the_firmware_upload_keeps_its_own():
    limits = re.findall(r"location (?:= )?(\S+) \{[^}]*?client_max_body_size (\S+);", _SITE, re.DOTALL)
    assert ("/api/v1/telemetry/batch", "600000") in limits
    assert ("/api/v1/firmware/upload", "3m") in limits
    assert len(limits) == 2 and re.search(r"^    client_max_body_size 64k;", _SITE, re.MULTILINE)


def test_the_error_pages_answer_in_the_apis_json_shape_with_stable_codes_and_never_a_wildcard():
    for status, name, code in (
        (429, "rate_limited", "rate_limited"), (413, "payload_too_large", "payload_too_large"),
        (502, "upstream_unavailable", "upstream_unavailable"), (504, "upstream_timeout", "upstream_timeout"),
    ):
        assert re.search(rf"error_page {status} @{name};", _SITE)
        block = re.search(rf"location @{name} \{{(.*?)\n    \}}", _SITE, re.DOTALL).group(1)
        assert f"return {status} '" in block and f'"code":"{code}"' in block and '"request_id":"$request_id"' in block
        for header in ("Strict-Transport-Security", "X-Content-Type-Options", "Cache-Control", "Access-Control-Allow-Origin",
                       "Access-Control-Allow-Credentials", "Vary"):
            assert header in block, (name, header)
        assert "default_type application/json" in block
    assert re.search(r'add_header Retry-After "\d+" always;', _SITE)
    assert not re.search(r"Access-Control-Allow-Origin\s+[\"']?\*", _SITE)


def _render_cors(tmp_path, allowed, credentialed=""):
    (tmp_path / "infra").mkdir(exist_ok=True)
    (tmp_path / "backend").mkdir(exist_ok=True)
    if not (tmp_path / "infra" / "scripts").exists():
        shutil.copytree(_SCRIPTS, tmp_path / "infra" / "scripts")
    (tmp_path / "backend" / ".env").write_text(f"ALLOWED_ORIGINS={allowed}\nCREDENTIALED_ORIGINS={credentialed}\n")
    return subprocess.run(["bash", str(tmp_path / "infra" / "scripts" / "render-cors.sh")], capture_output=True, text=True)


def _credentialed_origins(rendered):
    """The origins the credentials map names, read entry by entry, so a check compares whole origins."""
    block = re.search(r"phaemos_cors_credentials \{(.*?)\}", rendered, re.DOTALL).group(1)
    return set(re.findall(r'^\s*"([^"]+)" "true";$', block, re.MULTILINE))


@_NEEDS_TOOLS
def test_the_origins_file_follows_the_apis_rules_and_refuses_a_wildcard(tmp_path):
    out = _render_cors(tmp_path, "https://dash.example.org, https://example.org")
    assert out.returncode == 0
    # with no CREDENTIALED_ORIGINS the first allowed origin is the only credentialed one, as in the app
    assert _credentialed_origins(out.stdout) == {"https://dash.example.org"}
    out = _render_cors(tmp_path, "https://a.example.org,https://b.example.org", "https://b.example.org")
    assert _credentialed_origins(out.stdout) == {"https://b.example.org"}
    for bad in ("*", "https://*.example.org", "null", "https://example.org/path", "javascript:alert(1)"):
        assert _render_cors(tmp_path, bad).returncode != 0, bad


@_NEEDS_TOOLS
def test_the_nginx_check_fails_when_the_origins_file_no_longer_matches_backend_env(tree):
    _signed_release(tree)
    tree.write_env(ALLOWED_ORIGINS="https://dashboard.example.org,https://example.org,https://new.example.org")
    result = tree.run()
    assert result.returncode != 0 and "ALLOWED_ORIGINS" in result.stderr
