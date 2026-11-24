"""
The model file is a pickle, so it is signed. A file is read only when it lies in the model folder and is a signed
envelope this server made, keyed by a secret derived from the server's secret key for this purpose alone. A file that is
refused is never unpickled: every refusal below plants a payload that would write a marker file when unpickled and
checks that the marker is absent, not only that the file was refused.
"""
import io
import os
import threading

import joblib
import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from app.config import settings
from app.services import ml_service as ml


class _Payload:
    """Unpickling this writes a file at its path. Module level so it can be pickled."""

    def __init__(self, path):
        self.path = str(path)

    def __reduce__(self):
        return (open, (self.path, "w"))


def _forest():
    model = IsolationForest(n_estimators=5, random_state=1).fit(np.random.default_rng(1).normal(size=(50, 1)))
    model.phaemos_features = ["temperature"]
    model.phaemos_schema = ml.SCHEMA_VERSION
    return model


def _current_bundle():
    return {"default": _forest(), ml.META_KEY: {"format": ml.SCHEMA_VERSION}}


def _pickled(obj) -> bytes:
    buf = io.BytesIO()
    joblib.dump(obj, buf)
    return buf.getvalue()


@pytest.fixture
def folder(tmp_path, monkeypatch):
    path = tmp_path / "models" / "model.pkl"
    path.parent.mkdir()
    monkeypatch.setattr(ml, "MODEL_PATH", str(path))
    monkeypatch.setattr(ml, "_model", None)
    monkeypatch.setattr(ml, "_problem", None)
    monkeypatch.setattr(ml, "_load_failure", None)
    monkeypatch.setattr(ml, "_loaded_mtime", None)
    monkeypatch.setattr(ml, "_logged", set())
    yield path
    ml._model = None


@pytest.fixture
def marker(tmp_path):
    return tmp_path / "PAYLOAD_RAN"


def _refused_without_running(folder, marker):
    """The file in place is refused by the loader and the payload in it never ran."""
    ml._model = None
    ml._load_failure = None
    assert ml.model_state() == "error"
    assert ml._model is None
    assert not marker.exists(), "a refused model file was unpickled"
    with pytest.raises(ValueError):
        ml._load_file(str(folder))
    assert not marker.exists(), "a refused model file was unpickled"


def test_a_saved_file_is_one_signed_envelope_and_loads(folder):
    ml.save_model(_current_bundle())
    data = folder.read_bytes()
    assert data.startswith(ml.FILE_MAGIC)
    # no signature beside it: the signature is inside the file, so the pair can never be seen half replaced
    assert not (folder.parent / "model.pkl.sig").exists()
    assert ml.model_state() == "ok"


def test_an_unsigned_pickle_is_never_unpickled(folder, marker):
    folder.write_bytes(_pickled(_Payload(marker)))
    _refused_without_running(folder, marker)
    assert ml.UNSIGNED_REASON in ml.scoring_problem()


def test_an_unsigned_file_from_before_signing_is_refused_and_says_to_retrain(folder, marker):
    # the old layout: a plain pickle of a bundle without metadata. It is not accepted once as legacy any more
    folder.write_bytes(_pickled({"default": _Payload(marker)}))
    _refused_without_running(folder, marker)
    assert "Retrain to write a signed one: POST /api/v1/ml/retrain" in ml.scoring_problem()


def test_the_old_two_file_layout_is_refused_even_with_a_valid_signature_beside_it(folder, marker):
    import hashlib
    import hmac
    data = _pickled(_Payload(marker))
    folder.write_bytes(data)
    # the earlier version's .sig: the HMAC of the raw bytes. A file in that layout is never read
    (folder.parent / "model.pkl.sig").write_text(hmac.new(ml._signing_key(), data, hashlib.sha256).hexdigest())
    _refused_without_running(folder, marker)


def test_a_payload_behind_a_forged_signature_is_never_unpickled(folder, marker):
    payload = _pickled(_Payload(marker))
    folder.write_bytes(ml.FILE_MAGIC + b"0" * 64 + b"\n" + payload)
    _refused_without_running(folder, marker)
    assert ml.BAD_SIGNATURE_REASON in ml.scoring_problem()


def test_a_file_changed_after_it_was_signed_is_never_unpickled(folder, marker):
    ml.save_model(_current_bundle())
    data = folder.read_bytes()
    head = len(ml.FILE_MAGIC) + 65
    # the signature of the real file and the bytes of a payload
    folder.write_bytes(data[:head] + _pickled(_Payload(marker)))
    _refused_without_running(folder, marker)


def test_a_file_signed_with_another_key_is_never_unpickled(folder, marker, monkeypatch):
    original = settings.secret_key
    monkeypatch.setattr(settings, "secret_key", "another-secret-key-for-this-test-only-x")
    folder.write_bytes(ml._envelope(_pickled(_Payload(marker))))
    monkeypatch.setattr(settings, "secret_key", original)
    _refused_without_running(folder, marker)


def test_an_unsigned_previous_copy_is_never_unpickled_as_a_fallback(folder, marker):
    folder.write_bytes(b"broken")
    (folder.parent / "model.pkl.prev").write_bytes(_pickled(_Payload(marker)))
    _refused_without_running(folder, marker)


def test_the_previous_copy_is_signed_and_is_the_fallback(folder):
    ml.save_model(_current_bundle())
    ml.save_model(_current_bundle())
    assert (folder.parent / "model.pkl.prev").read_bytes().startswith(ml.FILE_MAGIC)
    folder.write_bytes(b"broken")
    ml._model = None
    assert ml.model_state() == "ok"


def test_a_broken_file_in_place_never_replaces_a_good_previous_copy(folder):
    ml.save_model(_current_bundle())
    ml.save_model(_current_bundle())
    good = (folder.parent / "model.pkl.prev").read_bytes()
    folder.write_bytes(b"broken")
    ml.save_model(_current_bundle())
    assert (folder.parent / "model.pkl.prev").read_bytes() == good


def test_the_signature_depends_on_the_servers_secret_key(folder, monkeypatch):
    ml.save_model(_current_bundle())
    monkeypatch.setattr(settings, "secret_key", "another-secret-key-for-this-test")
    ml._model = None
    assert ml.model_state() == "error"


def test_the_key_comes_from_the_one_place_that_derives_every_key():
    from app.services.keys import derive_key
    assert ml._signing_key() == derive_key("model_file")
    assert ml._signing_key() != settings.secret_key.encode() and len(ml._signing_key()) == 32
    assert ml._signing_key() != derive_key("access")


def test_a_file_signed_under_the_previous_key_verifies_and_is_signed_again_at_the_next_save(folder, monkeypatch):
    old_secret = settings.secret_key
    ml.save_model(_current_bundle())
    old = folder.read_bytes()
    monkeypatch.setattr(settings, "secret_key", "the-rotated-secret-key-for-this-test")
    monkeypatch.setattr(settings, "secret_key_previous", old_secret)
    ml._model = None
    assert ml.model_state() == "ok"
    ml.save_model(_current_bundle())
    assert folder.read_bytes()[:len(ml.FILE_MAGIC) + 64] != old[:len(ml.FILE_MAGIC) + 64]
    # the previous key is dropped and both files still load: each was signed again under the current one
    monkeypatch.setattr(settings, "secret_key_previous", "")
    ml._model = None
    assert ml.model_state() == "ok"
    ml._load_file(str(folder.parent / "model.pkl.prev"))


def test_a_model_is_never_read_from_outside_the_model_folder(folder, tmp_path, marker):
    signed = ml._envelope(_pickled(_Payload(marker)))
    outside = tmp_path / "elsewhere.pkl"
    outside.write_bytes(signed)
    with pytest.raises(ValueError, match="outside the model folder"):
        ml._load_file(str(outside))
    link = folder.parent / "link.pkl"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="outside the model folder"):
        ml._load_file(str(link))
    with pytest.raises(ValueError, match="outside the model folder"):
        ml._load_file(str(folder.parent / ".." / "elsewhere.pkl"))
    assert not marker.exists()


def test_a_model_path_that_is_a_link_out_of_the_folder_is_not_loaded(folder, tmp_path, marker):
    real = tmp_path / "real-model.pkl"
    real.write_bytes(ml._envelope(_pickled(_Payload(marker))))
    os.symlink(real, folder)
    _refused_without_running(folder, marker)


def test_a_reader_racing_a_writer_always_reads_a_whole_signed_file(folder):
    """A writer saves new bundles over and over while readers load: every read verifies and none falls back."""
    ml.save_model(_current_bundle())
    bundles = [_current_bundle() for _ in range(3)]
    stop = threading.Event()
    errors: list = []
    reads = [0]

    def writer():
        i = 0
        while not stop.is_set():
            ml.save_model(bundles[i % len(bundles)])
            i += 1

    def reader():
        while not stop.is_set():
            try:
                bundle = ml._load_file(str(folder))
                assert ml.META_KEY in bundle
                reads[0] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(2)]
    for t in threads:
        t.start()
    stop.wait(3.0)
    stop.set()
    for t in threads:
        t.join()
    assert reads[0] > 50 and errors == []


def test_the_acceptance_of_a_move_is_signed_and_a_forged_one_is_ignored(folder):
    ml.accept_move("dev-1", "admin-1")
    assert set(ml.accepted_moves()) == {"dev-1"}
    path = folder.parent / "model.pkl.accepted"
    path.write_bytes(b'{"dev-2": {"by": "nobody"}}')
    assert ml.accepted_moves() == {}


# -- which reason the operator is told ---------------------------------------------------------------------------------

def _unmonitored_bundle():
    bundle = _current_bundle()
    bundle[ml.META_KEY]["unmonitored"] = {"z": "its own model was refused: it caught 2 of 20 faults"}
    bundle[ml.META_KEY]["learning_node_types"] = {"pico_w": 1.0}
    return bundle


def _score_unmonitored():
    # a reading of a node type that is still learning, for a machine with no model of its own: no model may score it
    return ml.score_reading({"node_type": "pico_w", "temperature": 20.0}, device_id="z")


def test_a_bad_file_outranks_a_machines_own_reason_that_came_before_it(folder, marker):
    ml.save_model(_unmonitored_bundle())
    assert _score_unmonitored() == (None, False)
    assert ml.scoring_problem().startswith("no model is in service for this machine")
    # then the file is replaced by a planted one. Whatever is on record for the machine, the operator hears about the file
    folder.write_bytes(_pickled(_Payload(marker)))
    ml.reload_model()
    assert ml.scoring_problem() == f"the model file could not be loaded ({ml.UNSIGNED_REASON})"
    assert _score_unmonitored() == (None, False)
    assert ml.scoring_problem() == f"the model file could not be loaded ({ml.UNSIGNED_REASON})"
    assert not marker.exists()


def test_a_machines_own_reason_after_a_bad_file_is_fixed_is_its_own(folder, marker):
    folder.write_bytes(ml.FILE_MAGIC + b"0" * 64 + b"\n" + _pickled(_Payload(marker)))
    assert _score_unmonitored() == (None, False)
    assert ml.BAD_SIGNATURE_REASON in ml.scoring_problem()
    # a retrain writes a signed file: the file's problem is gone and the machine's own reason is what is said
    ml.save_model(_unmonitored_bundle())
    ml.reload_model()
    assert ml.scoring_problem() is None
    assert _score_unmonitored() == (None, False)
    assert ml.scoring_problem() == "no model is in service for this machine: its own model was refused: it caught 2 of 20 faults"
    assert not marker.exists()


def test_a_reading_reason_from_an_earlier_load_is_never_repeated(folder):
    ml.save_model(_unmonitored_bundle())
    _score_unmonitored()
    assert ml.scoring_problem() is not None
    # another worker's retrain replaced the file: the old note is about a model that is no longer loaded
    ml.save_model(_current_bundle())
    ml.reload_model()
    assert ml.scoring_problem() is None


def test_on_the_previous_file_a_worker_keeps_checking_the_main_one_even_if_its_time_did_not_change(folder):
    ml.save_model(_current_bundle())
    ml.save_model(_current_bundle())
    stamp = os.path.getmtime(folder)
    good = folder.read_bytes()
    # a half-written main file on a file system without an atomic rename
    folder.write_bytes(good[:200])
    os.utime(folder, (stamp, stamp))
    ml._model = None
    assert ml.model_state() == "ok" and ml._loaded_mtime == ml.FALLBACK_MTIME
    first = ml._model
    # the write completes and keeps the same time: the worker must still pick it up
    folder.write_bytes(good)
    os.utime(folder, (stamp, stamp))
    ml._next_check = 0.0
    ml._maybe_reload()
    assert ml._model is not first and ml._loaded_mtime == stamp
