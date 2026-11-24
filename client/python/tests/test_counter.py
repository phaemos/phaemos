import os
import stat

from phaemos_client.counter import MAX_BOOT, ReplayCounter, state_dir


def test_boot_rises_at_every_start_even_with_the_clock_set_back(tmp_path):
    a = ReplayCounter("key", tmp_path, clock=lambda: 1_800_000_000).boot
    b = ReplayCounter("key", tmp_path, clock=lambda: 1_800_000_000).boot
    c = ReplayCounter("key", tmp_path, clock=lambda: 1_700_000_000).boot
    assert a < b < c


def test_boot_starts_above_an_earlier_one_after_a_wipe(tmp_path):
    before = ReplayCounter("key", tmp_path, clock=lambda: 1_800_000_000).boot
    for item in tmp_path.iterdir():
        item.unlink()
    assert ReplayCounter("key", tmp_path, clock=lambda: 1_800_000_100).boot > before


def test_boot_never_exceeds_the_apis_limit(tmp_path):
    assert ReplayCounter("key", tmp_path, clock=lambda: 9_999_999_999).boot == MAX_BOOT


def test_each_key_has_its_own_file_and_the_key_is_not_in_the_name(tmp_path):
    ReplayCounter("secret-key-abc", tmp_path)
    ReplayCounter("other-key", tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2
    assert all("secret" not in n and len(n) < 40 for n in names)


def test_state_is_private(tmp_path):
    directory = tmp_path / "state"
    ReplayCounter("key", directory)
    assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700
    (file,) = directory.iterdir()
    assert stat.S_IMODE(os.stat(file).st_mode) == 0o600


def test_an_open_folder_gives_a_warning_but_a_working_boot(tmp_path):
    os.chmod(tmp_path, 0o777)
    counter = ReplayCounter("key", tmp_path, clock=lambda: 1_800_000_000)
    assert counter.warning
    assert counter.boot == 1_800_000_000


def test_no_state_folder_gives_a_warning_and_a_clock_boot():
    counter = ReplayCounter("key", None, clock=lambda: 1_800_000_000)
    assert counter.warning and counter.boot == 1_800_000_000


def test_stamp_adds_the_triple_and_leaves_the_callers_dict_alone(tmp_path):
    counter = ReplayCounter("key", tmp_path, monotonic=iter([10.0, 15.0, 20.0]).__next__)
    reading = {"device_id": "d"}
    one = counter.stamp(reading)
    two = counter.stamp(reading)
    assert reading == {"device_id": "d"}
    assert (one["seq"], two["seq"]) == (0, 1)
    assert (one["up"], two["up"]) == (5, 10)
    assert one["boot"] == two["boot"]


def test_state_dir_order():
    assert str(state_dir({"PHAEMOS_STATE_DIR": "/a", "HOME": "/h"})) == "/a"
    assert str(state_dir({"XDG_STATE_HOME": "/x", "HOME": "/h"})) == "/x/phaemos"
    assert str(state_dir({"HOME": "/h"})) == "/h/.local/state/phaemos"
    assert state_dir({}) is None
