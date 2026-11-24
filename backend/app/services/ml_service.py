"""
ML Service - trains, saves, loads and applies the anomaly models. A reading is scored to (anomaly_score, is_anomaly).

A machine has a model of its own when it has enough clean readings: an Isolation Forest, a per-sensor baseline
(services/baseline_check.py) and a sequential change detector (services/change_detector.py). The first
MAX_MACHINE_MODELS machines (oldest first) get all three. Every machine beyond that cap gets a light model of its own,
the baseline and the detector without the forest, which is a few kilobytes, so no machine is left to a pooled model
only because of the cap. One model per node type and one general model, pooled over machines, score a machine that has
no model of its own yet. What decides whether a score becomes an alert is in services/anomaly_decision.py.

How a score is made
-------------------
scikit-learn's IsolationForest.score_samples returns the opposite of the paper's anomaly score: a number between -1
and 0 where LOWER means more abnormal. We set offset_ ourselves to the boundary we measure (see fit_model) and map
decisions onto 0-1 so that the boundary is ANOMALY_THRESHOLD (0.7) and the typical healthy reading is 0. The baseline and
the detector are mapped onto the same scale and a reading's score is the largest of the three.

How a model is measured
-----------------------
A machine's clean readings are split by time into fit, validation and test parts (services/training_data.py). The
model is fitted on the fit part. Every boundary and every tightening is set on the validation part: the raw score only 1
reading in 1,000 of the healthy validation readings is worse than, then a replay of those readings through the real
alert decision, then a stricter quantile while the false alerts are over the budget. The detection check injects faults
into the validation readings. The test part is touched by nothing that is tuned: the false alert figure that is
reported, its 95 per cent interval and the champion and challenger comparison come from it alone.

A new model replaces the one in service only when it is not worse on the same newest readings (the champion and
challenger rule), when its detector boundary can be crossed and when it does not move the machine's normal further than
MAX_MOVE_FROM_SERVICE from the model in service or MAX_MOVE_FROM_ANCHOR from the first model a person accepted. A larger
move needs a person (accept_move). A model the retrain does not replace is carried over for at most CARRY_MAX_DAYS.

Ambient. A node that carries both an air temperature (its BME280) and a machine temperature (a contact probe or an
infrared sensor) is modelled on the machine's rise above the air and its room channels are context only: a warmer room
is then not a fault. A node with no such pair has no ambient reference. Its readings adapt slowly within a bound (see
the module notes of the baseline and the detector) and its status says it has no ambient reference.

A reading is scored only when it carries every feature its model needs. A missing feature is not zero: it means the
sensor was not measured (or was faulted). Such a reading gets a null score and counts as neither normal nor anomalous.

The model file is a signed envelope (see save_model). A file without this server's signature is never unpickled.
"""
import hashlib
import hmac
import io
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

# use joblib because it is the standard way to serialise scikit-learn models to and from disk
import joblib
# import numpy because scikit-learn models expect a numpy array, not a plain Python list
import numpy as np
from scipy.stats import chi2
from sklearn.ensemble import IsolationForest

from app.config import settings
from app.services import baseline_check as bl
from app.services import change_detector as cd
from app.services import model_evaluation as ev
from app.services import training_data as td
from app.services.anomaly_decision import BOUNDARY

logger = logging.getLogger(__name__)

# the path comes from settings (MODEL_PATH). Its default is the ml/ folder beside the code, which
# resolves the same wherever the app is launched from.
MODEL_PATH = settings.model_path
# classify a reading as anomalous when its normalised score reaches this threshold. It is the decision module's
# boundary: training maps its measured boundary onto it, so no reader of the score changes scale
ANOMALY_THRESHOLD = BOUNDARY
# the general model's features, used for readings that do not say which node sent them.
FEATURE_COLS = ["temperature", "humidity", "vibration_x", "vibration_y", "vibration_z", "light_level"]
# the model's columns: every sensor column and the site's ambient reference (training_data.MODEL_COLS)
SENSOR_COLS = td.MODEL_COLS
# a column belongs to a model when at least this share of its readings carry it
FIELD_PRESENCE = 0.9
# the general model uses the columns that at least this share of all readings carry. A fixed list would need every
# row to have every column, which no mixed fleet does
GENERAL_PRESENCE = 0.9
# written on every model this version trains. 4 is this design (three splits, time-weighted detector, slow adaptation,
# ambient plan). A bundle holding an older mark is not served: it is reported as legacy until a retrain
SCHEMA_VERSION = 4
# 100 trees is scikit-learn's own default and scores stably. Each tree is fitted on 1,024 readings and not the default
# 256. A tree can only split inside the range it saw, so a reading far outside it lands in the same leaf as the most
# extreme healthy reading. Deeper trees give that edge more leaves, which is what makes a fault that moves several
# sensors at once score above the boundary
N_ESTIMATORS = 100
MAX_SAMPLES = 1024
# fixed so a retrain on the same readings gives the same model
SEED = 42
# the per-sensor baseline beside the forest (services/baseline_check.py)
USE_BASELINE = True
# the sequential change detector beside them (services/change_detector.py), for a machine's own model only
USE_DETECTOR = True
# the smallest boundary of the detector, in standard-deviation minutes accumulated (change_detector.REF_S). A quiet
# validation period must not make it a hair trigger: 15 is a steady offset of the allowance plus one deviation for a
# quarter of an hour
DETECTOR_MIN_BOUNDARY = 15.0
# a detector boundary above this share of the accumulator's cap could hardly ever be crossed, so such a model is refused
DETECTOR_MAX_BOUNDARY_SHARE = 0.5
# how far the detector's boundary is moved beyond the validation quantile, as a share of its distance from typical
DETECTOR_MARGIN = 0.25
# how far the forest's measured boundary is moved from the typical reading, as a share of the distance between them
FOREST_MARGIN = 0.1
# the same for the baseline's boundary
BASELINE_MARGIN = 0.2
# fewest fit rows a model is trained on. A model with fewer has not seen enough of the machine to be measured
MIN_FIT_ROWS = 500
# at most this many machines get a full model (with the forest), oldest machines first. It is the setting
# ML_MAX_MACHINE_MODELS. A full model is about 3.6 MB on disk and about 3.5 MB in memory in every API worker once its trees
# are packed for scoring (measured: see docs/architecture.md), so 24 is about 85 MB a worker. Every machine beyond the
# cap gets a light model (baseline and detector, a few kilobytes) of its own
MAX_MACHINE_MODELS = settings.ml_max_machine_models
OVER_CAP_REASON = (
    "this deployment trains at most {cap} full machine models (with the forest), oldest machines first, so this machine "
    "has a light model of its own: the per-sensor baseline and the change detector without the forest. Raise "
    "ML_MAX_MACHINE_MODELS to give it the forest too, at about 3.5 MB a model in every worker"
)
# a challenger replaces the model in service unless it raises more false alerts than both the champion and the budget on
# the same test readings or catches this share fewer of the same injected faults
DETECTION_TOLERANCE = 0.1
# how far a retrain may move a machine's normal, in the in-state spreads of the reference model: from the model in
# service and from the anchor (the first model accepted for the machine or the last one a person accepted)
MAX_MOVE_FROM_SERVICE = 1.0
MAX_MOVE_FROM_ANCHOR = 2.0
# a model the retrain does not replace is carried over at most this long after it was trained and then withdrawn
CARRY_MAX_DAYS = 7
# the room channels of a node that also has a machine temperature: context for the expected value, not evidence of a fault
AMBIENT_COLS = ("temperature", "humidity", "pressure")
AIR_COL = "temperature"
SURFACE_COLS = ("contact_temp", "ir_temperature")
NO_AMBIENT_REASON = (
    "no ambient reference: this node has no air temperature beside a machine temperature and no other node is set as its "
    "ambient source (PUT /api/v1/ml/machines/{id}/ambient-source), so a warmer room cannot be told from a warmer machine at "
    "once. A slow change is followed within a bound instead"
)
# the key of the bundle's metadata. It is not a model
META_KEY = "__meta__"
# how often a worker checks whether another worker has written a newer model file
RELOAD_CHECK_SECONDS = 30.0

# start with None and populate on first use - lazy loading avoids disk I/O at import time
_model = None
# modification time of the file the loaded model came from and when it is next worth looking again
_loaded_mtime: float | None = None
_next_check = 0.0
# the packed trees of each model, kept by the model's id with the model itself so an id is never mistaken
_packed: dict[int, tuple] = {}
_local = threading.local()

# why the model file cannot be used right now or None. It is put in a reading's quality and in the no-scored-reading
# alert, so a model file that will not load is seen and not guessed at. A file that is simply absent is not a problem:
# readings pass through as 0.0 until one is trained. A failure while scoring one machine is that reading's problem only
# (see scoring_problem) and never the fleet's
_problem: str | None = None
# (modification time, reason) of a file that failed to load, so it is not read again on every post until it changes
_load_failure: tuple[float, str] | None = None
# problems already logged, so the log gets one line for a fault and not one per post
_logged: set[str] = set()


# bumped whenever the loaded model or the file's problem changes, so a reading's problem from before (another file,
# another load) is never reported as if it were about the model in place now
_generation = 0


def _note_reading_problem(reason: str | None) -> None:
    _local.problem = None if reason is None else (reason, _generation)


def scoring_problem() -> str | None:
    """
    Why readings are not being scored, in the order an operator must hear it.

    1. The model file cannot be used (_problem): it has no signature, fails its signature, lies outside the model folder
       or will not load. That is about every machine and may be a planted file, so it always comes first, whatever
       else is on record for a machine.
    2. The reading last scored in this thread had no score for a reason of its own (no model in service for its
       machine, a model from an earlier version, a failure while scoring it), as long as it was scored against the
       model that is loaded now. A reason left from an earlier load or a replaced file is dropped, never repeated.
    3. None.

    The second is thread-local: in the server it answers the question the ingest path asks straight after scoring a
    reading. Asked anywhere else (a status read in a worker thread that once scored another machine) it must not carry an
    old machine's reason, which is why it is tied to the load it came from and cleared at the start of every score.
    """
    if _problem:
        return _problem
    noted = getattr(_local, "problem", None)
    if noted is not None and noted[1] == _generation:
        return noted[0]
    return None


def _log_once(reason: str) -> None:
    if reason not in _logged:
        _logged.add(reason)
        logger.error("%s. Readings are stored without a score until it is fixed", reason)


def _models_in(bundle) -> list:
    if isinstance(bundle, dict):
        return [m for k, m in bundle.items() if k != META_KEY]
    return [bundle]


def _usable(bundle) -> bool:
    return all(hasattr(m, "score_samples") for m in _models_in(bundle))


def _is_old(bundle) -> bool:
    return any((getattr(m, "phaemos_schema", None) or 0) < SCHEMA_VERSION for m in _models_in(bundle))


def _meta(bundle=None) -> dict:
    bundle = _model if bundle is None else bundle
    return bundle.get(META_KEY) or {} if isinstance(bundle, dict) else {}


# -- the signed file ------------------------------------------------------------------------------------------------

def _signing_keys() -> list[bytes]:
    """The keys a model file may verify under: the current one for the purpose and then the previous one when set."""
    from app.services.keys import verification_keys
    return verification_keys("model_file")


def _signing_key() -> bytes:
    """The key a model file is signed with. It comes from services/keys.py, which derives one key per purpose."""
    return _signing_keys()[0]


# a model file is one signed envelope: this header, the hex HMAC of the header and the payload, a newline and then the
# pickled bundle. The signature travels inside the file, so the file and its signature are replaced by one rename and a
# reader can never see a new file beside an old signature or the other way round
FILE_MAGIC = b"PHAEMOS-SIGNED-MODEL-1\n"
_SIG_HEX = 64
UNSIGNED_REASON = (
    "the model file is not a model file signed by this server (it has no signature, was saved before signing or was "
    "replaced), so it was not read. Retrain to write a signed one: POST /api/v1/ml/retrain"
)
BAD_SIGNATURE_REASON = (
    "the model file does not match its signature (it was changed after it was saved or was signed with another key), so "
    "it was not read. Retrain to write a signed one: POST /api/v1/ml/retrain"
)


def _sign(data: bytes, key: bytes | None = None) -> str:
    return hmac.new(key or _signing_key(), FILE_MAGIC + data, hashlib.sha256).hexdigest()


def _envelope(payload: bytes) -> bytes:
    return FILE_MAGIC + _sign(payload).encode("ascii") + b"\n" + payload


def _open_envelope(data: bytes) -> bytes:
    """
    The payload of a signed envelope, checked against every key it may verify under. Raises ValueError otherwise.

    Nothing here unpickles: it only compares bytes, so a planted file can be refused without running any of its code.
    """
    head = len(FILE_MAGIC)
    if not data.startswith(FILE_MAGIC) or len(data) < head + _SIG_HEX + 1 or data[head + _SIG_HEX:head + _SIG_HEX + 1] != b"\n":
        raise ValueError(UNSIGNED_REASON)
    wanted = data[head:head + _SIG_HEX].decode("ascii", errors="replace")
    payload = data[head + _SIG_HEX + 1:]
    if not any(hmac.compare_digest(wanted, _sign(payload, key)) for key in _signing_keys()):
        raise ValueError(BAD_SIGNATURE_REASON)
    return payload


def _inside_model_folder(path: str) -> bool:
    """True when path, with any link followed, lies in the folder of MODEL_PATH. A model is never read from elsewhere."""
    folder = os.path.realpath(os.path.dirname(os.path.abspath(MODEL_PATH)))
    return os.path.realpath(path).startswith(folder + os.sep)


def _read_signed(path: str) -> bytes:
    """The verified payload of the model file at path or ValueError. It never unpickles."""
    if not _inside_model_folder(path):
        raise ValueError("the model file is outside the model folder")
    with open(path, "rb") as handle:
        data = handle.read()
    return _open_envelope(data)


def _load_file(path: str):
    """
    Read one model file after checking where it is and that it is the one this server wrote.

    A pickle runs code when it is read, so the signature is checked on the bytes and only a file that verifies is ever
    unpickled. A file without this server's signature is refused whatever it holds: there is no accepted-once path for
    files from before signing, because a file that claims to be one is exactly what a planted payload would claim.
    """
    payload = _read_signed(path)
    return joblib.load(io.BytesIO(payload))


def _load_model():
    # `global _model` is needed to assign to the module-level variable; without it Python would create a local one
    global _model, _problem, _load_failure, _loaded_mtime, _generation
    # only load from disk if not already loaded AND the file exists (model may not be trained yet)
    if _model is not None:
        return
    if not os.path.exists(MODEL_PATH):
        # a file that would not load and was then deleted by hand is no longer a problem: nothing is in place, which is the safe
        # pass-through and a new file is read when it appears
        _load_failure, _problem = None, None
        return
    modified = os.path.getmtime(MODEL_PATH)
    if _load_failure is not None and _load_failure[0] == modified:
        _problem = _load_failure[1]
        return
    reason = None
    # the file and then the copy of the one before it that save_model keeps
    for path in (MODEL_PATH, MODEL_PATH + ".prev"):
        if not os.path.exists(path):
            continue
        try:
            bundle = _load_file(path)
            if not _usable(bundle):
                raise ValueError("not a model")
        except Exception as exc:
            # the refusals of the signature check say what to do. Anything else is named by its type only. The words
            # are always one of the two fixed reasons, never the exception's own text, which can reach an API answer
            said = next((known for known in (UNSIGNED_REASON, BAD_SIGNATURE_REASON)
                         if isinstance(exc, ValueError) and exc.args == (known,)), None)
            reason = reason or f"the model file could not be loaded ({said or type(exc).__name__})"
            _log_once(reason if path == MODEL_PATH else f"the previous model file could not be loaded either ({said or type(exc).__name__})")
            continue
        # on the fallback the main file's time is not recorded: on a file system whose rename is not atomic the main file
        # may have failed only half written, so _maybe_reload must keep checking it and not wait for its time to change
        _model, _problem, _load_failure = bundle, None, None
        _loaded_mtime = modified if path == MODEL_PATH else FALLBACK_MTIME
        _generation += 1
        _packed.clear()
        if path != MODEL_PATH:
            logger.warning("the model file could not be loaded, so the previous one is in use until a retrain")
        if _is_old(_model):
            logger.warning("the model file was saved by an earlier version. It scores nothing until an admin retrains "
                           "(POST /api/v1/ml/retrain)")
        return
    _load_failure, _problem = (modified, reason), reason
    _generation += 1


# the loaded time recorded while the previous file is in use, which no real file time equals
FALLBACK_MTIME = -1.0


def _maybe_reload() -> None:
    """
    Pick up a model file another worker wrote, looking at most every RELOAD_CHECK_SECONDS.

    While the previous file is in use (the main one failed), the main file is checked by its signature alone, which reads
    and hashes it but never unpickles it and reloaded as soon as it verifies.
    """
    global _next_check
    if _model is None or _loaded_mtime is None:
        return
    now = time.monotonic()
    if now < _next_check:
        return
    _next_check = now + RELOAD_CHECK_SECONDS
    try:
        if _loaded_mtime == FALLBACK_MTIME:
            try:
                _read_signed(MODEL_PATH)
            except ValueError:
                return
            reload_model()
        elif os.path.getmtime(MODEL_PATH) != _loaded_mtime:
            reload_model()
    except OSError:
        pass


def model_state() -> str:
    """none (no file), ok, legacy (a signed file from an earlier version, not served) or error (it will not load)."""
    try:
        _load_model()
    except Exception:
        return "error"
    if _problem:
        return "error"
    if _model is None:
        return "none"
    return "legacy" if _is_old(_model) else "ok"


def _write_atomic(directory: str, target: str, data: bytes) -> None:
    """Write data to target through a synced temporary file in the same folder and one rename."""
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".model-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save_model(bundle) -> None:
    """
    Write the model file so that a crash, a full disk or a restart half way can never leave a broken file in place.

    The bundle is pickled in memory, wrapped in a signed envelope and written to a temporary file in the same folder,
    synced and renamed over the model file, which is one step on the same file system. The signature is inside the
    file, so a reader racing this writer sees either the old signed file or the new one and never a mismatched pair.
    The file it replaces is kept as MODEL_PATH.prev when its own signature verifies (checked on the bytes, never by
    unpickling), so a file that will not load has a fallback.
    """
    directory = os.path.dirname(os.path.abspath(MODEL_PATH))
    os.makedirs(directory, exist_ok=True)
    buf = io.BytesIO()
    joblib.dump(bundle, buf)
    data = _envelope(buf.getvalue())
    if os.path.exists(MODEL_PATH):
        try:
            # signed again under the current key, so a file signed under the previous key survives a key rotation
            _write_atomic(directory, MODEL_PATH + ".prev", _envelope(_read_signed(MODEL_PATH)))
        except Exception:
            # the file in place does not verify and a copy of it would replace a good fallback
            pass
    _write_atomic(directory, MODEL_PATH, data)
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _has_all(row: dict, cols: list[str]) -> bool:
    return all(row.get(c) is not None for c in cols)


def _matrix(rows: list[dict], cols: list[str]) -> np.ndarray:
    return np.array([[float(r[c]) for c in cols] for r in rows])


def _general_from_counts(counts: dict, total: int) -> list[str]:
    # the site reference belongs to one machine's own model and never to a pooled one
    pooled = [c for c in SENSOR_COLS if c != td.AMBIENT_REF and c in counts]
    cols = [c for c in pooled if counts[c] >= GENERAL_PRESENCE * total]
    if not cols:
        best = max(pooled, key=lambda c: counts[c])
        cols = [best] if counts[best] else []
    return cols


def general_features(rows: list[dict]) -> list[str]:
    """
    The columns the general model is trained on: those at least GENERAL_PRESENCE of all rows carry.

    When no column reaches that share (a fleet of very different nodes) the single most common column is used, so a
    deployment that has readings always ends up with some model able to score a reading that has that column.
    """
    if not rows:
        return []
    return _general_from_counts({c: sum(r.get(c) is not None for r in rows) for c in td.SENSOR_COLS}, len(rows))


# -- the numbers: scaling, scoring and the 0-1 scale -------------------------------------------------------------

def calibrate(model, raw_scores: np.ndarray) -> None:
    """Store how healthy readings scored, so later scores can be read against them (the median decision value)."""
    decisions = raw_scores - model.offset_
    model.phaemos_typical_decision = float(max(np.median(decisions), 1e-6))


def normalise(model, raw_scores: np.ndarray) -> np.ndarray:
    """
    Map raw Isolation Forest scores onto 0-1, higher meaning more anomalous.

    A typical healthy reading maps to 0 and the model's decision boundary (offset_) maps to ANOMALY_THRESHOLD. In a
    model this version trains offset_ is the boundary measured on validation readings.
    """
    typical = getattr(model, "phaemos_typical_decision", None)
    decisions = raw_scores - model.offset_
    if typical is None:
        typical = 0.1
    return np.clip(ANOMALY_THRESHOLD * (typical - decisions) / typical, 0.0, 1.0)


def _scale_of(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median and inter-quartile range of each column of the fit split. A column that never varies keeps scale 1."""
    center = np.median(X, axis=0)
    q1, q3 = np.percentile(X, [25, 75], axis=0)
    scale = q3 - q1
    std = X.std(axis=0)
    # an inter-quartile range of zero (a column that sits on one value most of the time) falls back to the deviation
    scale = np.where(scale > 1e-9, scale, np.where(std > 1e-9, std, 1.0))
    return center, scale


def _scaled(model, X: np.ndarray) -> np.ndarray:
    scaler = getattr(model, "phaemos_scaler", None)
    if scaler is None:
        return X
    return (X - scaler[0]) / scaler[1]


def _avg_path(n: np.ndarray) -> np.ndarray:
    n = np.asarray(n, dtype=float)
    out = np.zeros_like(n)
    out[n == 2] = 1.0
    big = n > 2
    out[big] = 2.0 * (np.log(n[big] - 1.0) + np.euler_gamma) - 2.0 * (n[big] - 1.0) / n[big]
    return out


def _pack(model) -> tuple:
    """
    Every tree of a fitted forest in five padded arrays, so one reading is scored with numpy and not tree by tree.

    scikit-learn's score_samples visits the trees one at a time through joblib, which costs about 15 ms for a single
    reading however small the forest. Walking all trees together costs a fraction of a millisecond. The numbers are
    the same: tests compare this against score_samples.
    """
    trees = [e.tree_ for e in model.estimators_]
    t_count, width = len(trees), max(t.node_count for t in trees)
    feature = np.zeros((t_count, width), dtype=np.int64)
    threshold = np.zeros((t_count, width))
    left = np.full((t_count, width), -1, dtype=np.int64)
    right = np.full((t_count, width), -1, dtype=np.int64)
    value = np.zeros((t_count, width))
    for i, tree in enumerate(trees):
        n = tree.node_count
        f = tree.feature.copy()
        f[f < 0] = 0
        feature[i, :n], threshold[i, :n] = f, tree.threshold
        left[i, :n], right[i, :n] = tree.children_left, tree.children_right
        # scikit-learn adds the node's depth and the average path length of the samples that reached a leaf, less one
        value[i, :n] = model._decision_path_lengths[i] + model._average_path_length_per_tree[i] - 1.0
    depth = max(t.max_depth for t in trees) + 1
    return feature, threshold, left, right, value, depth, float(_avg_path(np.array([model.max_samples_]))[0])


def _packed_for(model) -> tuple:
    entry = _packed.get(id(model))
    if entry is None or entry[0] is not model:
        entry = (model, _pack(model))
        _packed[id(model)] = entry
    return entry[1]


def raw_scores(model, X: np.ndarray, pack: tuple | None = None) -> np.ndarray:
    """score_samples of the model for the rows of X (already scaled). Lower is more abnormal, between -1 and 0."""
    if not hasattr(model, "estimators_"):
        # a stand-in or a model object from another library
        return np.asarray(model.score_samples(X), dtype=float)
    feature, threshold, left, right, value, depth, c_max = pack or _packed_for(model)
    # scikit-learn reads the rows as 32-bit floats, so the same is done here
    X = np.asarray(X, dtype=np.float32)
    trees = feature.shape[0]
    out = np.empty(len(X))
    for lo in range(0, len(X), 2000):
        part = X[lo:lo + 2000]
        rows = len(part)
        node = np.zeros(rows * trees, dtype=np.int64)
        tree_of = np.tile(np.arange(trees), rows)
        row_of = np.repeat(np.arange(rows), trees)
        # only the (reading, tree) pairs that have not reached a leaf keep walking, so the work is the average path
        # length and not the deepest one
        active = np.arange(rows * trees)
        while active.size:
            at_node, at_tree = node[active], tree_of[active]
            kids = left[at_tree, at_node]
            moving = kids >= 0
            active = active[moving]
            if not active.size:
                break
            at_node, at_tree, kids = at_node[moving], at_tree[moving], kids[moving]
            seen = part[row_of[active], feature[at_tree, at_node]]
            node[active] = np.where(seen <= threshold[at_tree, at_node], kids, right[at_tree, at_node])
        total = value[tree_of, node].reshape(rows, trees).sum(axis=1)
        out[lo:lo + 2000] = -(2.0 ** (-total / (trees * c_max)))
    return out


class LightModel:
    """
    A machine model without the forest: the per-sensor baseline and the change detector carry it alone.

    It is what a machine beyond the cap on full models gets. It is a few kilobytes, so any number of them fit in memory.
    score_samples is the typical healthy forest value for any reading, so the forest's part of the score is always 0.
    """

    offset_ = -0.5
    phaemos_typical_decision = 1.0
    phaemos_has_forest = False

    def score_samples(self, X):
        return np.full(len(X), 0.5)


def _has_forest(model) -> bool:
    return bool(getattr(model, "phaemos_has_forest", True))


# -- the ambient plan: rise above the air ----------------------------------------------------------------------------

def ambient_plan(cols: list[str]) -> dict | None:
    """
    How a model uses the room or None when the machine has no ambient reference.

    Its own pair comes first: an air temperature and at least one machine temperature on the same node. The machine
    temperatures are modelled as their rise above the air and the room channels are context, inputs to the detector's
    expected values that are never watched themselves. Failing that, the site's reference (another node in the same
    place, the device's ambient_source_id): the machine's temperatures, its only temperature included, are modelled as
    their rise above that reading and the reference is context.
    """
    rise = [c for c in SURFACE_COLS if c in cols]
    if AIR_COL in cols and rise:
        return {"air": AIR_COL, "rise": rise, "context": [c for c in AMBIENT_COLS if c in cols], "source": "own"}
    if td.AMBIENT_REF in cols:
        rise = rise or ([AIR_COL] if AIR_COL in cols else [])
        if rise:
            # the node's other room channels (its humidity and pressure) are context too: a warmer, drier week is the room
            room = [c for c in AMBIENT_COLS if c in cols and c not in rise]
            return {"air": td.AMBIENT_REF, "rise": rise, "context": [td.AMBIENT_REF] + room, "source": "site"}
    return None


def machine_columns(cols: list[str]) -> list[str]:
    """
    A machine model's columns. The site reference is kept only where it is the machine's reference: a node with its own
    air temperature beside a machine temperature uses that pair and a node with no temperature has nothing to judge
    against the room, so for either the reference would only be one more room channel to raise false alerts on.
    """
    if td.AMBIENT_REF not in cols:
        return cols
    own = AIR_COL in cols and any(c in cols for c in SURFACE_COLS)
    has_temperature = AIR_COL in cols or any(c in cols for c in SURFACE_COLS)
    if own or not has_temperature:
        return [c for c in cols if c != td.AMBIENT_REF]
    return cols


def _derived(model_or_plan, X: np.ndarray, cols: list[str] | None = None) -> np.ndarray:
    """The model's columns as it reads them: a machine temperature becomes its rise above the air when the plan says so."""
    if isinstance(model_or_plan, dict) or model_or_plan is None:
        plan = model_or_plan
    else:
        plan = getattr(model_or_plan, "phaemos_ambient", None)
        cols = cols or list(getattr(model_or_plan, "phaemos_features", []))
    if not plan:
        return X
    Y = np.array(X, dtype=float, copy=True)
    air = cols.index(plan["air"])
    for name in plan["rise"]:
        Y[..., cols.index(name)] -= Y[..., air]
    return Y


def _context_mask(cols: list[str], plan: dict | None) -> np.ndarray:
    context = set(plan["context"]) if plan else set()
    return np.array([c in context for c in cols], dtype=bool)


def _forest_idx(model) -> list[int]:
    idx = getattr(model, "phaemos_forest_idx", None)
    return list(range(len(getattr(model, "phaemos_features", []) or []))) if idx is None else list(idx)


# -- scoring: the parts and their combination --------------------------------------------------------------------------

def _forest_raw(model, Xd: np.ndarray, pack: tuple | None = None) -> np.ndarray:
    """The forest's raw scores for derived rows Xd (the model's columns, rise applied)."""
    if not _has_forest(model):
        return np.full(len(Xd), 0.5)
    part = Xd[:, _forest_idx(model)] if getattr(model, "phaemos_forest_idx", None) is not None else Xd
    return raw_scores(model, _scaled(model, part), pack)


def score_parts(model, X: np.ndarray, pack: tuple | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    """The forest's normalised scores for the rows of X (raw columns) and the baseline's (None without one), with no state."""
    Xd = _derived(model, X)
    forest = normalise(model, _forest_raw(model, Xd, pack)) if _has_forest(model) else np.zeros(len(X))
    baseline = getattr(model, "phaemos_baseline", None)
    return forest, None if baseline is None else bl.normalise(baseline, bl.raw_scores(baseline, Xd))


def combine(model, parts: dict) -> np.ndarray:
    """The 0-1 score of each reading from the raw parts: the largest of the forest, the baseline and the detector."""
    n = len(parts["baseline"] if parts.get("baseline") is not None else parts["forest"])
    out = normalise(model, parts["forest"]) if _has_forest(model) and parts.get("forest") is not None else np.zeros(n)
    baseline = getattr(model, "phaemos_baseline", None)
    if baseline is not None and parts.get("baseline") is not None:
        out = np.maximum(out, bl.normalise(baseline, parts["baseline"]))
    detector = getattr(model, "phaemos_detector", None)
    if detector is not None and parts.get("detector") is not None:
        out = np.maximum(out, cd.normalise(detector, parts["detector"]))
    return out


def _base_update(baseline, state, s: int, x: np.ndarray, weight_s: float, t: float) -> np.ndarray:
    """
    Follow the slow level of each sensor in the reading's operating state s and return the reading with it taken off.

    The level is a time-weighted average of the reading's distance from its state's median over cd.LEVEL_TAU_S, clipped
    to the baseline's level_bound. It moves only when time moves (weight_s > 0). After a cold start (or a retrain, whose
    baseline draws its states afresh) it is for cd.WARMUP_S the running mean of the machine's own readings in that state,
    so the forest and the baseline judge a machine against where it is now and not against the training data's level.
    """
    bound = baseline.level_bound
    if state.base_level is None or state.base_level.shape != bound.shape:
        state.base_level = np.zeros_like(bound)
        state.base_n = np.zeros(len(bound))
        state.base_from = t if state.base_from is None else state.base_from
    if state.base_n is None or len(state.base_n) != len(bound):
        state.base_n = np.zeros(len(bound))
    warming = state.base_from is not None and t - state.base_from < cd.WARMUP_S
    dev = x - baseline.median[s]
    if warming:
        if weight_s > 0 or state.base_n[s] == 0:
            state.base_n[s] += 1
            state.base_level[s] = np.clip(state.base_level[s] + (dev - state.base_level[s]) / state.base_n[s],
                                          -bound[s], bound[s])
        return x - state.base_level[s]
    adjusted = x - state.base_level[s]
    if weight_s > 0:
        a = 1.0 - np.exp(-weight_s / cd.LEVEL_TAU_S)
        state.base_level[s] = np.clip(state.base_level[s] + a * (dev - state.base_level[s]), -bound[s], bound[s])
    return adjusted


def _base_level_step(baseline, state, x: np.ndarray, weight_s: float, t: float = 0.0) -> np.ndarray:
    """_base_update for one reading, choosing its operating state from all its sensors."""
    if getattr(baseline, "level_bound", None) is None:
        return x
    return _base_update(baseline, state, int(bl.state_of(baseline, x[None])[0]), x, weight_s, t)


def _model_id(model) -> str | None:
    return getattr(model, "phaemos_id", None)


def _fresh_state(model) -> cd.DetectorState:
    """
    A machine's state when nothing can be carried: a cold start.

    Its slow levels are not taken from training. For the detector's warm-up they are the running mean of the machine's
    own readings (change_detector.step and _base_levels), so a machine starts from where it is now, not from where the
    training data was days ago. The detector holds its alerts for that warm-up (change_detector.WARMUP_S).
    """
    return cd.DetectorState(model_id=_model_id(model), interval_s=getattr(model, "phaemos_interval_s", None))


# a state is carried across a retrain when the new model reads the same sensors on scales within this factor of the old
CARRY_SCALE_FACTOR = 2.0


def _basis(detector) -> dict:
    return {"cols": list(detector.cols), "center": np.asarray(detector.center, dtype=float).tolist(),
            "scale": np.asarray(detector.scale, dtype=float).tolist(), "boundary": float(detector.boundary)}


def carry_state(state: cd.DetectorState, model, t: float | None = None) -> cd.DetectorState | None:
    """
    A machine's state re-expressed for a new model (after a retrain) or None when it cannot be carried.

    It can be carried when the new model's detector reads the same sensors in the same order and its scales are within
    CARRY_SCALE_FACTOR of the old ones. The smoothed views are moved into the new model's units, so no warm-up is needed.
    The accumulators keep their share of the boundary, so an alert that was building or open does not vanish at night.
    The residual levels are moved into the new units and the per-state levels, whose states the new baseline draws
    afresh, are read again from the machine's readings over the next warm-up. Anything else starts cold.
    """
    detector = getattr(model, "phaemos_detector", None)
    basis = state.basis
    if detector is None or not basis or list(basis.get("cols") or []) != list(detector.cols) or state.smooth is None:
        return None
    old_c, old_s = np.array(basis["center"], dtype=float), np.array(basis["scale"], dtype=float)
    if old_s.shape != detector.scale.shape:
        return None
    ratio = detector.scale / np.maximum(old_s, 1e-12)
    if np.any(ratio > CARRY_SCALE_FACTOR) or np.any(ratio < 1.0 / CARRY_SCALE_FACTOR):
        return None
    out = cd.DetectorState(model_id=_model_id(model), interval_s=state.interval_s, last_t=state.last_t,
                           warm_from=state.warm_from, steps=state.steps)
    out.smooth = ((state.smooth * old_s + old_c) - detector.center) / detector.scale
    share = float(detector.boundary) / max(float(basis.get("boundary") or detector.boundary), 1e-9)
    if state.s_pos is not None:
        out.s_pos, out.s_neg = state.s_pos * share, state.s_neg * share
        out.since_pos, out.since_neg = state.since_pos, state.since_neg
        out.area_pos = None if state.area_pos is None else state.area_pos * old_s / detector.scale
        out.area_neg = None if state.area_neg is None else state.area_neg * old_s / detector.scale
    if state.level is not None:
        bound = detector.level_bound if detector.level_bound is not None else np.full(len(detector.cols), np.inf)
        out.level = np.clip(state.level * old_s / detector.scale, -bound, bound) * detector.active
    out.base_level, out.base_from = None, t if t is not None else state.last_t
    out.basis = _basis(detector)
    return out# the present level of a run is read from its readings over this long
PRESENT_S = 3600.0


def _present_levels(model, times: np.ndarray, Xd: np.ndarray) -> tuple:
    """
    The slow levels the given readings show: the mean residual of each watched sensor and the mean distance of each
    sensor from its state's median, each clipped to its bound. Used to start a machine's levels where its readings are.
    """
    level = base = None
    detector = getattr(model, "phaemos_detector", None)
    if detector is not None and len(times) >= 10:
        r = cd.residuals(detector, times, Xd)
        settle = times >= times[0] + 600.0 if times[-1] - times[0] > 1200.0 else np.ones(len(times), dtype=bool)
        bound = detector.level_bound if detector.level_bound is not None else np.full(r.shape[1], np.inf)
        level = np.clip(r[settle].mean(axis=0), -bound, bound) * detector.active
    baseline = getattr(model, "phaemos_baseline", None)
    if baseline is not None and baseline.level_bound is not None and len(times):
        states = bl.state_of(baseline, Xd)
        base = np.zeros_like(baseline.level_bound)
        for s in range(baseline.states):
            inside = states == s
            if inside.sum() >= 10:
                dev = (Xd[inside] - baseline.median[s]).mean(axis=0)
                base[s] = np.clip(dev, -baseline.level_bound[s], baseline.level_bound[s])
    return level, base


def _observe_interval(model, state: cd.DetectorState, dt: float | None) -> float:
    """
    The machine's posting interval as its readings show it: a slow average of the gaps, kept within bounds.

    A gap longer than twenty times the current figure is a silence and not a new interval.
    """
    trained = float(getattr(model, "phaemos_interval_s", None) or 5.0)
    current = float(state.interval_s or trained)
    if dt is not None and 0 < dt <= 20.0 * current:
        current += 0.05 * (dt - current)
    current = min(max(current, max(trained / 20.0, 1.0)), trained * 20.0)
    state.interval_s = current
    return current


def score_step(model, state: cd.DetectorState, t: float, x: np.ndarray) -> tuple[float, dict]:
    """
    Score one reading in time order and update the machine's state in place. Returns (0-1 score, raw parts).

    The forest and the baseline judge the reading with its slow per-state level taken off. The detector steps on the
    reading itself (its own residual level lives inside it). A reading at or before the last one moves nothing.
    """
    x = np.asarray(x, dtype=float)
    xd = _derived(model, x[None])[0]
    dt = None if state.last_t is None else t - state.last_t
    weight = 0.0 if dt is None or dt <= 0 else min(dt, cd.MAX_STEP_S)
    interval = _observe_interval(model, state, dt if dt is not None and dt > 0 else None)
    baseline = getattr(model, "phaemos_baseline", None)
    adjusted = _base_level_step(baseline, state, xd, weight, float(t)) if baseline is not None else xd
    parts = {"forest": _forest_raw(model, adjusted[None]),
             "baseline": None if baseline is None else bl.raw_scores(baseline, adjusted[None]), "detector": None}
    detector = getattr(model, "phaemos_detector", None)
    if detector is not None:
        parts["detector"] = np.array([cd.step(detector, state, float(t), xd, interval)])
        state.basis = _basis(detector)
    elif dt is None or dt > 0:
        state.last_t = float(t)
        state.steps += 1
    return float(combine(model, parts)[0]), parts


def sequence_parts(model, times: np.ndarray, X: np.ndarray, interval_s: float | None = None,
                   state: cd.DetectorState | None = None, pause: np.ndarray | None = None, prime: bool = False) -> dict:
    """
    The raw parts for a run of readings in time order, as the live path would score them one by one from state.

    It is score_step in a loop, written so the forest and the baseline are scored in one batch. pause (optional, one
    flag per reading) marks readings in a maintenance window: they are scored without stepping and the detector
    restarts after the window, as score_reading does. prime starts the slow levels at the level the run's first hour
    shows, which is what a machine in service has: its levels have followed it all along. Measurements on held-out
    readings prime, so a run is not judged against the level of the fit rows days earlier.
    """
    state = state or _fresh_state(model)
    if interval_s is not None and state.interval_s is None:
        state.interval_s = float(interval_s)
    X = np.asarray(X, dtype=float)
    Xd = _derived(model, X)
    if prime and len(times):
        first = np.asarray(times) < float(times[0]) + PRESENT_S
        level, base = _present_levels(model, np.asarray(times, dtype=float)[first], Xd[first])
        if level is not None:
            state.level = level
        if base is not None:
            # primed levels are known already, so no cold warm-up follows
            state.base_level, state.base_n, state.base_from = base, np.zeros(len(base)), float(times[0]) - cd.WARMUP_S - 1.0
    baseline = getattr(model, "phaemos_baseline", None)
    detector = getattr(model, "phaemos_detector", None)
    adjusted = Xd.copy()
    det_raw = np.zeros(len(X)) if detector is not None else None
    bound = getattr(baseline, "level_bound", None) if baseline is not None else None
    states = bl.state_of(baseline, Xd) if bound is not None else None
    for i in range(len(X)):
        t = float(times[i])
        dt = None if state.last_t is None else t - state.last_t
        if pause is not None and pause[i]:
            if bound is not None:
                adjusted[i] = _base_update(baseline, state, int(states[i]), Xd[i], 0.0, t)
            _pause(state)
            if det_raw is not None:
                det_raw[i] = 0.0
            continue
        weight = 0.0 if dt is None or dt <= 0 else min(dt, cd.MAX_STEP_S)
        interval = _observe_interval(model, state, dt if dt is not None and dt > 0 else None)
        if bound is not None:
            adjusted[i] = _base_update(baseline, state, int(states[i]), Xd[i], weight, t)
        if det_raw is not None:
            det_raw[i] = cd.step(detector, state, t, Xd[i], interval)
        elif dt is None or dt > 0:
            state.last_t = t
            state.steps += 1
    if detector is not None:
        state.basis = _basis(detector)
    return {"forest": _forest_raw(model, adjusted), "detector": det_raw,
            "baseline": None if baseline is None else bl.raw_scores(baseline, adjusted)}


def score_sequence(model, times, X, interval_s=None, state=None, pause=None, prime=False) -> np.ndarray:
    """0-1 scores for a run of one machine's readings in time order, exactly as the live path scores them."""
    return combine(model, sequence_parts(model, np.asarray(times, dtype=float), X, interval_s, state, pause, prime))


def score_matrix(model, X: np.ndarray, pack: tuple | None = None, times=None, interval_s=None) -> np.ndarray:
    """
    Normalised 0-1 scores for the rows of X, which hold the model's features in order and are not yet derived or scaled.

    With the epoch times of the rows it is score_sequence from a fresh state (the detector and the slow levels take
    part). Without them it is the forest and the baseline on each reading alone.
    """
    if times is not None and (getattr(model, "phaemos_detector", None) is not None
                              or getattr(getattr(model, "phaemos_baseline", None), "level_bound", None) is not None):
        return score_sequence(model, times, X, interval_s, prime=True)
    forest, baseline = score_parts(model, X, pack)
    return forest if baseline is None else np.maximum(forest, baseline)


def _pause(state: cd.DetectorState) -> None:
    """A maintenance window: the detector's run is ended so the window's end starts a fresh warm-up. The levels stay."""
    state.smooth = None
    state.s_pos = state.s_neg = None
    state.since_pos = state.since_neg = None
    state.area_pos = state.area_neg = None
    state.warm_from = None


# -- fitting one model and measuring it -----------------------------------------------------------------------------

@dataclass
class Scope:
    """The readings one model is trained and measured on."""

    key: str
    scope: str
    label: str
    cols: list[str]
    fit: np.ndarray
    segments: list
    clean_hours: float
    span_hours: float
    refused: dict = field(default_factory=dict)
    # a machine's own scope carries the times of its fit rows and its interval, for the change detector
    fit_times: np.ndarray | None = None
    interval_s: float = 5.0
    # the newest readings, for the reported figures and the champion comparison only
    tests: list = field(default_factory=list)
    # a machine beyond the cap on full models: no forest
    light: bool = False


def _poisson_interval(count: int, weeks: float) -> tuple[float | None, float | None]:
    """The exact (Garwood) 95 per cent interval of a rate per week from count events in weeks."""
    if weeks <= 0:
        return None, None
    lo = 0.0 if count == 0 else float(chi2.ppf(0.025, 2 * count) / 2.0)
    hi = float(chi2.ppf(0.975, 2 * count + 2) / 2.0)
    return lo / weeks, hi / weeks


def arl_bounds(crossings: int, hours: float) -> dict:
    """
    The average run length between false crossings of the detector's boundary, honestly stated.

    With crossings seen it is hours / crossings with a one-sided 95 per cent lower bound. With none seen the run length is
    censored: it is only known to be longer than the 95 per cent lower bound hours / 3.0 (the bound for zero events).
    """
    lower = hours / (float(chi2.ppf(0.95, 2 * crossings + 2)) / 2.0) if hours > 0 else 0.0
    return {"crossings": int(crossings), "hours_watched": round(hours, 1), "censored": crossings == 0,
            "arl_hours": None if crossings == 0 else round(hours / crossings, 1), "arl_hours_lower_95": round(lower, 1)}


def _false_alerts(segments: list, fn) -> dict:
    rate = ev.false_alert_rate(segments, fn)
    weeks = (rate["heldout_hours"] or 0.0) / (7 * 24.0)
    lo, hi = _poisson_interval(rate["alerts"], weeks)
    return {"alerts": rate["alerts"], "hours": rate["heldout_hours"],
            "per_week": None if rate["per_machine_week"] is None else round(rate["per_machine_week"], 3),
            "per_week_low_95": None if lo is None else round(lo, 3), "per_week_high_95": None if hi is None else round(hi, 3)}


def fit_model(scope: Scope) -> tuple:
    """
    Fit one model on scope.fit, set every threshold on scope.segments (validation) and report on scope.tests.

    Returns (model or None, record). The record always says what happened. When the model is None the record's
    "message" says why in words an operator can act on. See the module note for the measurement.
    """
    record = {
        "key": scope.key, "scope": scope.scope, "label": scope.label, "features": scope.cols,
        "rows_fit": int(len(scope.fit)), "rows_heldout": int(sum(len(s.times) for s in scope.segments)),
        "rows_test": int(sum(len(s.times) for s in scope.tests)),
        "clean_hours": round(scope.clean_hours, 2), "span_hours": round(scope.span_hours, 2),
        "rows_refused": dict(scope.refused), "state": "refused", "message": "",
        "false_alerts_per_week": None, "heldout_hours": None, "boundary": None, "quantile": None,
        "tightenings": 0, "detection": None, "budget_per_week": ev.BUDGET_PER_WEEK, "light": scope.light,
        "validation": None, "test": None,
    }
    test_hours = sum(len(s.times) * s.interval_s for s in scope.tests) / 3600.0
    if len(scope.fit) < MIN_FIT_ROWS or record["rows_heldout"] < ev.MIN_HELDOUT_ROWS or test_hours < td.MIN_TEST_HOURS:
        record["state"] = "learning"
        record["message"] = (
            f"{scope.label} has {len(scope.fit)} training readings, {record['rows_heldout']} held back for setting its "
            f"limits and {test_hours:.1f} hours held back for testing. It needs at least {MIN_FIT_ROWS}, "
            f"{ev.MIN_HELDOUT_ROWS} and {td.MIN_TEST_HOURS:.0f} hours. It stays in learning and is not scored by a "
            "model of its own until it has them, so leave it running."
        )
        return None, record
    cols = list(scope.cols)
    plan = ambient_plan(cols) if scope.scope == "machine" else None
    fit_d = _derived(plan, scope.fit, cols)
    context = _context_mask(cols, plan)
    forest_idx = [i for i in range(len(cols)) if not context[i]] or list(range(len(cols)))
    model = LightModel() if scope.light else None
    if model is None:
        center, scale = _scale_of(fit_d[:, forest_idx])
        model = IsolationForest(
            n_estimators=N_ESTIMATORS, max_samples=min(MAX_SAMPLES, len(scope.fit)), contamination="auto",
            random_state=SEED,
        )
        model.fit((fit_d[:, forest_idx] - center) / scale)
        model.phaemos_scaler = (center, scale)
        model.phaemos_has_forest = True
    model.phaemos_features = cols
    model.phaemos_forest_idx = forest_idx
    model.phaemos_ambient = plan
    model.phaemos_schema = SCHEMA_VERSION
    model.phaemos_id = uuid.uuid4().hex
    model.phaemos_interval_s = float(scope.interval_s)
    model.phaemos_trained_at = datetime.now(timezone.utc).isoformat()
    pack = _pack(model) if _has_forest(model) else None

    # the baseline: each sensor's normal range per operating state, fitted on the fit rows. With the fit times it also
    # learns how far each level wanders, which bounds the slow adaptation
    fit_times = scope.fit_times if scope.fit_times is not None and len(scope.fit_times) == len(scope.fit) else None
    baseline = bl.fit(fit_d, cols, fit_times if scope.scope == "machine" else None) if USE_BASELINE else None
    if baseline is not None:
        baseline.extra["watch"] = (~context).tolist()
        baseline.extra["plan"] = plan
        # each sensor's own healthy tail, from the validation and fit readings: the stricter of the two 1 in 1,000
        # distances and never under one spread
        val_d = np.vstack([bl.distances(baseline, _derived(plan, seg.X, cols)) for seg in scope.segments])
        fit_dist = bl.distances(baseline, fit_d)
        baseline.sensor_scale = np.maximum(np.maximum(np.quantile(val_d, 1.0 - ev.QUANTILES[0], axis=0),
                                                      np.quantile(fit_dist, 1.0 - ev.QUANTILES[0], axis=0)), 1.0)
        model.phaemos_baseline = baseline
    detector = None
    if (USE_DETECTOR and fit_times is not None and scope.scope == "machine" and len(scope.fit) >= MIN_FIT_ROWS
            and len(cols) > 1):
        detector = cd.fit(fit_d, fit_times, cols)
        # a room channel is context: the expected values use it and it is never watched itself
        detector.active = detector.active & ~context
        detector.extra["interval_s"] = scope.interval_s
        # the level's bound is read from how far the residual wanders on the validation readings, which the regression
        # never saw: in-sample residuals understate it
        seen = np.max([cd.wander(cd.residuals(detector, seg.times, _derived(plan, seg.X, cols)), seg.times)
                       for seg in scope.segments], axis=0)
        detector.level_bound = cd.LEVEL_BOUND * np.maximum(seen, detector.quiet_sd)
        model.phaemos_detector = detector
    if scope.light and detector is None:
        record["message"] = (f"{scope.label} cannot have a light model: it has too few sensors for the change detector. "
                             "It is scored by its node type's model when there is one.")
        return None, record

    # the validation readings are scored once, as the live path would, from a fresh state. Tightening a boundary only
    # changes how the same raw parts are read
    parts = {id(s.X): sequence_parts(model, s.times, s.X, s.interval_s, prime=True) for s in scope.segments}
    raw_f = np.concatenate([parts[id(s.X)]["forest"] for s in scope.segments])
    raw_fit = _forest_raw(model, fit_d, pack) if _has_forest(model) else None
    if _has_forest(model):
        median = float(np.median(np.concatenate([raw_f, raw_fit])))
    if baseline is not None:
        raw_b = np.concatenate([parts[id(s.X)]["baseline"] for s in scope.segments])
        raw_b_fit = bl.raw_scores(baseline, fit_d)
        baseline.typical = float(np.median(np.concatenate([raw_b, raw_b_fit])))
    if detector is not None:
        raw_d = np.concatenate([parts[id(s.X)]["detector"] for s in scope.segments])
        detector.typical = float(np.median(raw_d))

    def score_fn(X, times=None, interval_s=None):
        if times is None:
            return score_matrix(model, X, pack)
        return score_sequence(model, times, X, interval_s, prime=True)

    def held_fn(X, times=None, interval_s=None):
        hit = parts.get(id(X))
        return score_fn(X, times, interval_s) if hit is None else combine(model, hit)

    rate = None
    for step, quantile in enumerate(ev.QUANTILES):
        if _has_forest(model):
            boundary = float(min(np.quantile(raw_f, quantile), np.quantile(raw_fit, quantile)))
            boundary -= FOREST_MARGIN * (median - boundary)
            if median - boundary < 1e-6:
                record["message"] = (
                    f"{scope.label} reads the same value on almost every held-back reading, so no boundary can be "
                    "measured. Check that its sensors are not stuck, then retrain."
                )
                return None, record
            model.offset_ = boundary
            model.phaemos_typical_decision = median - boundary
            record["boundary"] = round(boundary, 6)
        if baseline is not None:
            top = float(max(np.quantile(raw_b, 1.0 - quantile), np.quantile(raw_b_fit, 1.0 - quantile)))
            baseline.boundary = max(top + BASELINE_MARGIN * (top - baseline.typical), baseline.typical + 1e-6)
        if detector is not None:
            top = float(np.quantile(raw_d, 1.0 - quantile))
            detector.boundary = max(top + DETECTOR_MARGIN * (top - detector.typical), DETECTOR_MIN_BOUNDARY)
            crossings = sum(int(((p["detector"][1:] > detector.boundary) & (p["detector"][:-1] <= detector.boundary)).sum())
                            for p in parts.values())
            hours = sum(len(seg.times) * seg.interval_s for seg in scope.segments) / 3600.0
            bounds = arl_bounds(crossings, hours)
            detector.arl_hours = bounds["arl_hours"]
            detector.extra["arl"] = bounds
            record["detector"] = {"boundary": round(detector.boundary, 2), **bounds}
        rate = _false_alerts(scope.segments, held_fn)
        record.update(quantile=quantile, tightenings=step, validation=rate,
                      false_alerts_per_week=rate["per_week"], heldout_hours=rate["hours"], alerts_heldout=rate["alerts"])
        if rate["per_week"] is not None and rate["per_week"] <= ev.BUDGET_PER_WEEK:
            break
    else:
        record["message"] = (
            f"{scope.label} would still have raised {record['false_alerts_per_week']:.1f} false alerts per machine "
            f"per week on healthy readings it did not train on, after tightening its limit {len(ev.QUANTILES) - 1} "
            f"times. The budget is {ev.BUDGET_PER_WEEK:.0f}. The model in service is untouched. Let the machine run "
            "a few more normal days and retrain. Also look for a sensor that wanders."
        )
        return None, record
    if detector is not None and detector.boundary > DETECTOR_MAX_BOUNDARY_SHARE * cd.S_CAP:
        record["message"] = (
            f"{scope.label}'s change detector measured a boundary of {detector.boundary:.0f}, above "
            f"{DETECTOR_MAX_BOUNDARY_SHARE:.0%} of its cap of {cd.S_CAP:.0f}, so it could hardly ever raise an alert. The "
            "model in service is untouched. Look for a sensor that wanders or a change of duty in the last fortnight, "
            "then retrain."
        )
        return None, record
    found = ev.detection(scope.segments, cols, score_fn)
    record["detection"] = found
    if not found["trials"]:
        record["message"] = (
            f"{scope.label} could not be checked for detection: none of its held-back runs of readings is long enough to "
            "inject a fault into. A model that has not been checked is not put in service. The model in service is "
            "untouched. Retrain once the machines have run longer without gaps."
        )
        return None, record
    if found["missed_share"] > ev.MAX_MISSED_SHARE:
        record["message"] = (
            f"{scope.label} caught {found['caught']} of {found['trials']} faults injected into healthy readings and "
            f"at least {round(100 * (1 - ev.MAX_MISSED_SHARE))} per cent are needed. A model that finds too few faults is not worth "
            "having. The model in service is untouched. Retrain once more of the machine's range of normal "
            "behaviour has been recorded."
        )
        return None, record
    if detector is not None:
        # from here on the accumulators are capped at a few boundaries (change_detector.CAP_BOUNDARIES)
        detector.extra["measured"] = True
    # the reported figures: the test readings, which nothing above has seen
    test = _false_alerts(scope.tests, score_fn)
    test["detection"] = ev.detection(scope.tests, cols, score_fn)
    record["test"] = test
    record["false_alerts_per_week"] = test["per_week"]
    record["false_alerts_per_week_high_95"] = test["per_week_high_95"]
    record["state"] = "ready"
    record["message"] = ""
    model.phaemos_record = record
    return model, record


def evaluate_on(model, segments: list) -> dict:
    """A model's false alerts and detection on the given segments (its own columns), for the champion comparison."""
    def fn(X, times=None, interval_s=None):
        return score_sequence(model, times, X, interval_s, prime=True) if times is not None else score_matrix(model, X)
    out = _false_alerts(segments, fn)
    out["detection"] = ev.detection(segments, list(model.phaemos_features), fn)
    return out


# -- how far a retrain moves a machine's normal ------------------------------------------------------------------------

def baseline_move(new, ref, X: np.ndarray, cols: list[str]) -> dict:
    """
    How far the new model's normal sits from the reference model's for the same operating conditions, per sensor.

    For each fit row of the new model, the median of its operating state in the new model is compared with the median of
    its state in the reference model, in the reference's in-state spread. The median of that over the rows is the move.
    Rows are raw readings in cols order. Only sensors both models carry are compared.
    """
    nb = getattr(new, "phaemos_baseline", None)
    rb = ref if isinstance(ref, bl.Baseline) else getattr(ref, "phaemos_baseline", None)
    if nb is None or rb is None:
        return {}
    ref_cols = list(rb.cols)
    ref_plan = getattr(ref, "phaemos_ambient", None) if not isinstance(ref, bl.Baseline) else rb.extra.get("plan")
    new_plan = getattr(new, "phaemos_ambient", None)
    if (ref_plan is None) != (new_plan is None):
        return {}
    common = [c for c in cols if c in ref_cols]
    if not common or not len(X) or not all(c in cols for c in ref_cols):
        return {}
    Xn = _derived(new_plan, X, cols)
    Xr = _derived(ref_plan, X[:, [cols.index(c) for c in ref_cols]], ref_cols)
    sn, sr = bl.state_of(nb, Xn), bl.state_of(rb, Xr)
    out = {}
    for c in common:
        jn, jr = cols.index(c), ref_cols.index(c)
        diff = (nb.median[sn, jn] - rb.median[sr, jr]) / np.maximum(rb.spread[sr, jr], 1e-9)
        out[c] = round(float(np.median(diff)), 3)
    return out


def _anchor_of(model):
    """The baseline a machine's moves are measured from: the model's anchor, else its own baseline."""
    anchor = getattr(model, "phaemos_anchor", None)
    return anchor if anchor is not None else getattr(model, "phaemos_baseline", None)


def _acceptance_path() -> str:
    return MODEL_PATH + ".accepted"


def accepted_moves() -> dict:
    """The machines a person has allowed to move further than the bounds at the next retrain (signed, never pickled)."""
    try:
        payload = _read_signed(_acceptance_path())
        data = json.loads(payload.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def accept_move(device_id: str, by: str) -> None:
    """Allow the next retrain to move this machine's normal past the bounds and to re-anchor it there. A person's call."""
    directory = os.path.dirname(os.path.abspath(MODEL_PATH))
    os.makedirs(directory, exist_ok=True)
    data = accepted_moves()
    data[str(device_id)] = {"by": str(by), "at": datetime.now(timezone.utc).isoformat()}
    _write_atomic(directory, _acceptance_path(), _envelope(json.dumps(data).encode("utf-8")))


def _consume_acceptances(keys: Iterable[str]) -> None:
    data = accepted_moves()
    left = {k: v for k, v in data.items() if k not in set(keys)}
    if left != data:
        directory = os.path.dirname(os.path.abspath(MODEL_PATH))
        _write_atomic(directory, _acceptance_path(), _envelope(json.dumps(left).encode("utf-8")))


# -- training the bundle -------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    """What a retrain did. bundle is None when nothing was accepted and the serving model must be left alone."""

    status: str
    bundle: dict | None
    models: list
    summary: str
    learning: list = field(default_factory=list)
    # machines with no working model after this retrain: device id to the reason in words
    unmonitored: dict = field(default_factory=dict)
    # machines whose new model would move their normal too far: device id to the message
    moves: dict = field(default_factory=dict)
    # the machine acceptances this retrain used, to be cleared once the bundle is saved
    used_acceptances: list = field(default_factory=list)

    def result(self) -> dict:
        return {"status": self.status, "summary": self.summary, "models": self.models, "learning": self.learning,
                "unmonitored": self.unmonitored, "moves": self.moves}


def _select(blocks: list[np.ndarray], presence: float = FIELD_PRESENCE) -> list[str]:
    """The columns that at least `presence` of the stacked rows carry."""
    stacked = np.vstack([b for b in blocks if len(b)]) if any(len(b) for b in blocks) else np.empty((0, len(SENSOR_COLS)))
    if not len(stacked):
        return []
    have = (~np.isnan(stacked)).sum(axis=0)
    return [c for c, n in zip(SENSOR_COLS, have) if n >= presence * len(stacked)]


def _complete(X: np.ndarray, idx: list[int]) -> tuple[np.ndarray, int]:
    """The rows of X that carry every wanted column, cut to those columns with the count of rows left out."""
    part = X[:, idx]
    keep = ~np.isnan(part).any(axis=1)
    return part[keep], int((~keep).sum())


def _segments(helds, idx) -> tuple[list, int]:
    segments, dropped = [], 0
    for machine, X, times in helds:
        Xc, gone = _complete(X, idx)
        dropped += gone
        if gone:
            # a held-out row without a column is cut, which would leave a hole inside a run. Keep the time axis
            keep = ~np.isnan(X[:, idx]).any(axis=1)
            times = times[keep]
        if len(Xc):
            segments.append(ev.Segment(machine.device_id, machine.interval_s, times, Xc))
    return segments, dropped


def _scope_from(key, kind, label, cols, fits, helds, clean_hours, span_hours, refused, fit_times=None, interval_s=5.0,
                tests=None, light=False) -> Scope:
    idx = [SENSOR_COLS.index(c) for c in cols]
    parts = [_complete(f, idx) for f in fits]
    kept_times = None
    if fit_times is not None and len(fits) == 1 and len(fit_times) == len(fits[0]):
        kept_times = fit_times[~np.isnan(fits[0][:, idx]).any(axis=1)]
    fit = np.vstack([part[0] for part in parts]) if parts else np.empty((0, len(cols)))
    dropped = sum(part[1] for part in parts)
    segments, gone = _segments(helds, idx)
    test_segments, gone_test = _segments(tests or [], idx)
    dropped += gone + gone_test
    refused = dict(refused)
    if dropped:
        refused["missing_value"] = refused.get("missing_value", 0) + dropped
    return Scope(key, kind, label, cols, fit, segments, clean_hours, span_hours, refused, kept_times, interval_s,
                 test_segments, light)


def machine_segments(m: "td.MachineData", cols: list[str]) -> tuple[list, list]:
    """A machine's validation and test segments for the given columns (to score another model on the same readings)."""
    idx = [SENSOR_COLS.index(c) for c in cols]
    val, _ = _segments([(m, m.val, m.val_times)], idx)
    test, _ = _segments([(m, m.test, m.test_times)], idx)
    return val, test


class _Pool:
    """
    Rows pooled from many machines for a node type or the general model.

    Every machine gives an equal share of the fit rows. The held-out parts come from at most td.POOL_HELD_MACHINES
    machines spread evenly through the fleet, each with a long enough run to inject faults into.
    """

    def __init__(self, label: str, machines: int):
        self.label = label
        share = max(machines, 1)
        self.fit_share = td.POOL_FIT_ROWS // share
        held_machines = min(share, td.POOL_HELD_MACHINES)
        self.held_share = td.POOL_HELDOUT_ROWS // held_machines
        self.pick = set(np.linspace(0, share - 1, held_machines).round().astype(int).tolist())
        self.fits: list[np.ndarray] = []
        self.helds: list = []
        self.tests: list = []
        self.hours = 0.0
        self.span = 0.0
        self.refused: dict = {}
        self.machines = 0

    def add(self, m: "td.MachineData") -> None:
        if self.machines in self.pick:
            self.helds.append((m, td.thin_latest(m.val, self.held_share), td.thin_latest(m.val_times, self.held_share)))
            self.tests.append((m, td.thin_latest(m.test, self.held_share), td.thin_latest(m.test_times, self.held_share)))
        self.machines += 1
        self.fits.append(td.thin_evenly(m.fit, self.fit_share))
        self.hours += m.clean_hours
        self.span = max(self.span, m.span_hours)
        for reason, n in m.refused.items():
            self.refused[reason] = self.refused.get(reason, 0) + n


def _describe_refused(refused: dict) -> str:
    names = {**td.REFUSAL_REASONS, "missing_value": "lacked a value the model needs"}
    return "; ".join(f"{n} readings {names.get(r, r)}" for r, n in sorted(refused.items()))


def _age_days(model, now: datetime) -> float | None:
    stamp = getattr(model, "phaemos_trained_at", None)
    if not stamp:
        return None
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds() / 86400.0
    except ValueError:
        return None


def _champion_check(model, record, champion, m, cols) -> str | None:
    """None when the challenger may replace the champion, else the reason it may not, in words."""
    if champion is None or (getattr(champion, "phaemos_schema", 0) or 0) < SCHEMA_VERSION:
        return None
    try:
        champ_cols = list(champion.phaemos_features)
        _, champ_tests = machine_segments(m, champ_cols)
        if not champ_tests:
            return None
        champ = evaluate_on(champion, champ_tests)
    except Exception as exc:  # noqa: BLE001
        logger.warning("the model in service could not be measured on the new test readings (%s)", type(exc).__name__)
        return None
    chall = record.get("test") or {}
    record["champion"] = {"alerts": champ["alerts"], "per_week": champ["per_week"],
                          "caught": champ["detection"]["caught"], "trials": champ["detection"]["trials"]}
    budget_alerts = ev.BUDGET_PER_WEEK * (chall.get("hours") or 0.0) / (7 * 24.0)
    worse_alerts = (chall.get("alerts") or 0) > max(champ["alerts"], budget_alerts)
    c_det, k_det = chall.get("detection") or {}, champ["detection"]
    c_share = c_det.get("caught", 0) / c_det["trials"] if c_det.get("trials") else None
    k_share = k_det["caught"] / k_det["trials"] if k_det.get("trials") else None
    worse_detection = c_share is not None and k_share is not None and c_share < k_share - DETECTION_TOLERANCE
    if worse_alerts:
        return (f"The new model raised {chall.get('alerts')} false alerts on the newest {chall.get('hours') or 0:.0f} hours "
                f"of healthy readings where the model in service raised {champ['alerts']}, so the model in service is kept.")
    if worse_detection:
        return (f"The new model caught {c_det.get('caught')} of {c_det.get('trials')} faults injected into the newest "
                f"readings where the model in service caught {k_det['caught']} of {k_det['trials']}, so the model in "
                "service is kept.")
    return None


def _move_check(model, champion, m, cols, accepted: bool) -> tuple[str | None, dict]:
    """None when the move from the model in service and from the anchor is inside the bounds, else the reason."""
    moves = {}
    if champion is None:
        return None, moves
    fit = m.fit[:, [SENSOR_COLS.index(c) for c in cols]]
    fit = fit[~np.isnan(fit).any(axis=1)]
    from_service = baseline_move(model, champion, fit, cols)
    anchor = _anchor_of(champion)
    from_anchor = baseline_move(model, anchor if isinstance(anchor, bl.Baseline) else champion, fit, cols) \
        if anchor is not None else {}
    moves = {"from_service": from_service, "from_anchor": from_anchor}
    if accepted:
        return None, moves
    worst_s = max(from_service.items(), key=lambda kv: abs(kv[1]), default=(None, 0.0))
    worst_a = max(from_anchor.items(), key=lambda kv: abs(kv[1]), default=(None, 0.0))
    if abs(worst_s[1]) > MAX_MOVE_FROM_SERVICE or abs(worst_a[1]) > MAX_MOVE_FROM_ANCHOR:
        sensor, size, bound, what = ((worst_s[0], worst_s[1], MAX_MOVE_FROM_SERVICE, "the model in service")
                                     if abs(worst_s[1]) > MAX_MOVE_FROM_SERVICE else
                                     (worst_a[0], worst_a[1], MAX_MOVE_FROM_ANCHOR, "the first model accepted for it"))
        return (f"The new model would move this machine's normal {sensor} by {abs(size):.1f} of its usual spreads from "
                f"{what} (the bound is {bound:.1f}). A slow walk like that is what a drifting fault or a forged sensor "
                "looks like, so the model in service is kept and a person must accept the move: POST "
                f"/api/v1/ml/machines/{m.device_id}/accept-move, then retrain."), moves
    return None, moves


def train_bundle(
    machines: Iterable["td.MachineData"], node_counts: dict, total_machines: int,
    previous: dict | None = None, now: datetime | None = None,
) -> Outcome:
    """
    Train the machine, node type and general models from machines' clean readings and decide what goes in service.

    machines is read once and may be a generator that loads one machine at a time. node_counts says how many machines
    each node type has and total_machines how many there are, so every machine's share of a pool is known up front.
    previous is the serving bundle: a model this retrain does not accept is carried over from it for at most
    CARRY_MAX_DAYS. Returns an Outcome. Its bundle is None when no model was accepted and then nothing may be saved.
    """
    now = now or datetime.now(timezone.utc)
    previous = previous if isinstance(previous, dict) else {}
    accepted_by_person = accepted_moves()
    pools = {nt: _Pool(f"the {nt} node type", n) for nt, n in node_counts.items() if nt}
    general = _Pool("the general model", total_machines)
    records: list[dict] = []
    new: dict = {}
    machine_info: dict = {}
    seen_ids: set = set()
    full_models = 0
    moves: dict = {}
    used: list = []
    for m in machines:
        seen_ids.add(m.device_id)
        machine_info[m.device_id] = {
            "clean_hours": round(m.clean_hours, 2), "span_hours": round(m.span_hours, 2),
            "rows_refused": dict(m.refused), "scope": "learning", "node_type": m.node_type,
            "hours_needed": round(m.hours_needed, 1), "interval_s": m.interval_s,
            "recorded_interval_s": m.recorded_interval_s,
        }
        if m.node_type in pools:
            pools[m.node_type].add(m)
        general.add(m)
        if not m.enough or not len(m.fit) or not len(m.held):
            continue
        light = full_models >= MAX_MACHINE_MODELS
        if light:
            machine_info[m.device_id]["over_cap"] = True
            machine_info[m.device_id]["reason"] = OVER_CAP_REASON.format(cap=MAX_MACHINE_MODELS)
        cols = machine_columns(_select([m.fit, m.held]))
        if not cols:
            continue
        key = f"machine:{m.device_id}"
        scope = _scope_from(key, "machine", m.name, cols, [m.fit], [(m, m.val, m.val_times)],
                            m.clean_hours, m.span_hours, m.refused, m.fit_times, m.interval_s,
                            tests=[(m, m.test, m.test_times)], light=light)
        model, record = fit_model(scope)
        record["device_id"] = m.device_id
        records.append(record)
        champion = previous.get(key)
        if model is not None:
            why = _champion_check(model, record, champion, m, cols)
            accepted = str(m.device_id) in accepted_by_person
            moved, moves_seen = _move_check(model, champion, m, cols, accepted) if why is None else (None, {})
            if moves_seen:
                record["moves"] = moves_seen
            if why is not None or moved is not None:
                record["state"] = "refused"
                record["message"] = why or moved
                if moved is not None:
                    moves[m.device_id] = moved
                model = None
            else:
                # the anchor travels with the machine's models until a person accepts a larger move
                anchor = _anchor_of(champion) if (champion is not None and not accepted) else None
                model.phaemos_anchor = anchor if anchor is not None else model.phaemos_baseline
                if accepted:
                    used.append(str(m.device_id))
        if model is not None:
            new[key] = model
            if not light:
                full_models += 1
            machine_info[m.device_id]["scope"] = "machine"
            machine_info[m.device_id]["light"] = light
        else:
            machine_info[m.device_id]["scope"] = "refused" if record["state"] == "refused" else "learning"
    learning_nodes: dict = {}
    for nt, pool in sorted(pools.items()):
        if not pool.machines:
            continue
        if pool.hours < td.MIN_CLEAN_HOURS or pool.span < td.MIN_SPAN_HOURS:
            learning_nodes[nt] = round(pool.hours, 2)
            records.append({
                "key": nt, "scope": "node_type", "label": pool.label, "state": "learning",
                "clean_hours": round(pool.hours, 2), "span_hours": round(pool.span, 2), "rows_refused": dict(pool.refused),
                "message": f"{pool.label} has {pool.hours:.1f} of {td.MIN_CLEAN_HOURS:.0f} hours of clean readings. "
                           "It is not scored until it has a day of them, so leave it running.",
            })
            continue
        cols = [c for c in _select(pool.fits + [h[1] for h in pool.helds]) if c != td.AMBIENT_REF]
        if not cols:
            continue
        scope = _scope_from(nt, "node_type", pool.label, cols, pool.fits, pool.helds, pool.hours, pool.span, pool.refused,
                            tests=pool.tests)
        model, record = fit_model(scope)
        records.append(record)
        if model is not None:
            new[nt] = model
    if general.machines:
        if general.hours >= td.MIN_CLEAN_HOURS and general.span >= td.MIN_SPAN_HOURS:
            stacked_blocks = general.fits + [h[1] for h in general.helds]
            counts_rows = np.vstack([b for b in stacked_blocks if len(b)]) if any(len(b) for b in stacked_blocks) else None
            if counts_rows is not None and len(counts_rows):
                have = (~np.isnan(counts_rows)).sum(axis=0)
                cols = _general_from_counts(dict(zip(SENSOR_COLS, have)), len(counts_rows))
                if cols:
                    scope = _scope_from("default", "general", general.label, cols, general.fits, general.helds,
                                        general.hours, general.span, general.refused, tests=general.tests)
                    model, record = fit_model(scope)
                    records.append(record)
                    if model is not None:
                        new["default"] = model
        else:
            records.append({
                "key": "default", "scope": "general", "label": general.label, "state": "learning",
                "clean_hours": round(general.hours, 2), "span_hours": round(general.span, 2),
                "rows_refused": dict(general.refused),
                "message": f"{general.label} has {general.hours:.1f} of {td.MIN_CLEAN_HOURS:.0f} hours of clean readings.",
            })
    accepted = sorted(new)
    kept = []
    expired = {}
    bundle: dict = {}
    # a model that was not accepted is carried over from the bundle in service, so a retrain never takes a model away at
    # once. It is withdrawn once it is older than CARRY_MAX_DAYS: a model that keeps being refused describes a machine
    # that has changed and an old model kept for ever is what holds a stale alert open
    for key, model in previous.items():
        if key == META_KEY:
            continue
        if key.startswith("machine:") and key.split(":", 1)[1] not in seen_ids:
            continue
        if key in new:
            continue
        age = _age_days(model, now)
        if age is not None and age > CARRY_MAX_DAYS:
            expired[key] = age
            continue
        bundle[key] = model
        kept.append(key)
    bundle.update(new)
    for record in records:
        if record["key"] in kept and record["state"] != "ready":
            record["kept_previous"] = True
            age = _age_days(bundle[record["key"]], now)
            record["message"] = (record.get("message") or "") + (
                f" The model in service was trained {age:.1f} days ago and is withdrawn after {CARRY_MAX_DAYS} days if no "
                "new model is accepted." if age is not None else "")
        if record["key"] in expired:
            record["message"] = (record.get("message") or "") + (
                f" The model in service was trained {expired[record['key']]:.1f} days ago, more than {CARRY_MAX_DAYS} days, "
                "and has been withdrawn, so this machine has no working model until a retrain is accepted.")
    unmonitored = {}
    for device_id, info in machine_info.items():
        key = f"machine:{device_id}"
        if key in bundle:
            continue
        node = info.get("node_type")
        if node and node in bundle:
            continue
        if "default" in bundle and node not in learning_nodes:
            continue
        record = next((r for r in records if r["key"] == key), None)
        reason = (record or {}).get("message") or info.get("reason") or (
            f"it has {info['clean_hours']:.1f} of the {info['hours_needed']:.0f} hours of clean readings a model needs "
            "and no node type or general model can score it yet")
        unmonitored[device_id] = reason.strip()
        info["monitored"] = False
        info["unmonitored_reason"] = reason.strip()
    summary = _summary(records, accepted, kept, unmonitored, len(machine_info))
    if not accepted:
        return Outcome("refused", None, records, summary, _learning_lines(records), unmonitored, moves)
    bundle[META_KEY] = {
        "format": SCHEMA_VERSION, "trained_at": now.isoformat(), "machines": machine_info,
        "learning_node_types": learning_nodes,
        "models": {r["key"]: {k: r.get(k) for k in ("scope", "state", "false_alerts_per_week", "false_alerts_per_week_high_95",
                                                    "clean_hours", "span_hours", "light")}
                   for r in records if r["state"] == "ready"},
        "hours_needed": td.MIN_CLEAN_HOURS, "unmonitored": unmonitored,
    }
    return Outcome("trained", bundle, records, summary, _learning_lines(records), unmonitored, moves, used)


def _learning_lines(records: list[dict]) -> list[str]:
    return [r["message"] for r in records if r["state"] == "learning" and r.get("message")]


def _summary(records: list[dict], accepted: list[str], kept: list[str], unmonitored: dict | None = None,
             machines: int = 0) -> str:
    ready = [r for r in records if r["state"] == "ready"]
    refused = [r for r in records if r["state"] == "refused"]
    learning = [r for r in records if r["state"] == "learning"]
    if not ready and not refused and not learning:
        return "Retrain skipped: there are no clean readings in the last 14 days to learn from. The model in service is untouched."
    parts = []
    if ready:
        worst = max((r["false_alerts_per_week"] or 0.0) for r in ready)
        parts.append(f"{len(ready)} models accepted (worst false alert rate on the newest held-back readings {worst:.2f} "
                     "per machine per week)")
    if refused:
        parts.append(f"{len(refused)} refused: " + " ".join(r["message"] for r in refused))
    if learning:
        parts.append(f"{len(learning)} still learning")
    text = "Retrain: " + "; ".join(parts) + "."
    if not accepted:
        text += " The model in service is untouched."
    elif kept:
        text += f" {len(kept)} models in service were carried over."
    if unmonitored:
        text += f" {len(unmonitored)} of {machines} machines have no working model and are not monitored by the model."
    return text


# -- the status of what is in service --------------------------------------------------------------------------------

def _last_retrain_path() -> str:
    return MODEL_PATH + ".last.json"


def save_last_retrain(result: dict) -> None:
    """Keep the outcome of the latest retrain (accepted or refused) beside the model file, written in one step."""
    directory = os.path.dirname(os.path.abspath(MODEL_PATH))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".retrain-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(result, handle, default=float)
        os.replace(tmp, _last_retrain_path())
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def last_retrain() -> dict | None:
    try:
        with open(_last_retrain_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _record_of(model) -> dict:
    return getattr(model, "phaemos_record", None) or {}


def _ambient_words(model) -> str | None:
    if model is None or not hasattr(model, "phaemos_features"):
        return None
    plan = getattr(model, "phaemos_ambient", None)
    if plan and plan.get("source") == "site":
        return (f"the site's ambient reference (the air temperature of the node set as this machine's ambient source): "
                f"{', '.join(plan['rise'])} judged as rise above it")
    if plan:
        return (f"its own air temperature: {', '.join(plan['rise'])} judged as rise above it; {', '.join(plan['context'])} "
                "are context only")
    return NO_AMBIENT_REASON


def _model_status(device_id, node_type) -> dict:
    """
    The model state for one machine, for the device read and the dashboard. See model_status for the keys.

    It never touches the database: it reads the loaded bundle, so it is cheap enough for a list of machines.
    """
    status = {"state": "none", "scope": None, "hours_collected": None, "hours_needed": None,
              "false_alerts_per_week": None, "false_alerts_per_week_high_95": None, "trained_at": None,
              "refusal": None, "refused_at": None, "monitored": False, "reason": None, "ambient": None, "light": False}
    try:
        _load_model()
    except Exception:
        return {**status, "state": "error", "reason": "the model file could not be loaded"}
    if _problem:
        return {**status, "state": "error", "reason": _problem}
    if _model is None:
        return {**status, "reason": "no model has been trained yet: run a retrain (POST /api/v1/ml/retrain)"}
    bundle = _model
    if not isinstance(bundle, dict) or _is_old(bundle):
        return {**status, "state": "legacy", "reason": "the model file was saved by an earlier version and scores nothing "
                "until a retrain"}
    meta = _meta(bundle)
    info = (meta.get("machines") or {}).get(str(device_id)) or {}
    # the node type its readings carried at training is the one scoring looks models up by
    node_type = info.get("node_type") or node_type
    machine_key = f"machine:{device_id}"
    if machine_key in bundle:
        key, scope = machine_key, "machine"
    elif node_type and node_type in bundle:
        key, scope = node_type, "node_type"
    elif node_type and node_type in (meta.get("learning_node_types") or {}):
        key, scope = None, None
    elif "default" in bundle:
        key, scope = "default", "general"
    else:
        key, scope = None, None
    hours_needed = info.get("hours_needed") or td.hours_needed(info.get("interval_s") or 5.0)
    trained = meta.get("trained_at")
    if key is None:
        collected = info.get("clean_hours")
        if collected is None and node_type:
            collected = (meta.get("learning_node_types") or {}).get(node_type)
        collected = collected if collected is not None else 0.0
        reason = (meta.get("unmonitored") or {}).get(str(device_id)) or info.get("unmonitored_reason")
        # enough clean hours and still no model means the new model was refused (refusal and GET /ml/status say why)
        state = "learning" if collected < hours_needed else "none"
        return {**status, "state": state, "hours_collected": collected, "hours_needed": hours_needed, "trained_at": trained,
                "reason": reason or ("no model is in service for this machine, so the model raises no anomaly alert for it"
                                     if state == "none" else
                                     f"learning: {collected:.1f} of {hours_needed:.0f} hours of clean readings collected")}
    model = bundle[key]
    record = (meta.get("models") or {}).get(key) or _record_of(model)
    collected = info.get("clean_hours") if scope == "machine" else record.get("clean_hours")
    return {
        **status, "state": "ready", "scope": scope,
        "hours_collected": collected if collected is not None else record.get("clean_hours"),
        "hours_needed": hours_needed, "false_alerts_per_week": record.get("false_alerts_per_week"),
        "false_alerts_per_week_high_95": record.get("false_alerts_per_week_high_95"),
        "trained_at": trained, "monitored": True, "light": bool(getattr(model, "phaemos_has_forest", True) is False),
        "ambient": _ambient_words(model) if scope == "machine" else None,
        "reason": info.get("reason") if scope == "machine" else (
            "scored by a pooled model: it has no model of its own yet" if scope else None),
    }


_refusal_cache: dict = {"mtime": None, "data": {}}


def _refusals() -> dict:
    """The models the latest retrain refused, key to (message, finished_at). The sidecar is read again only when it changes."""
    try:
        mtime = os.path.getmtime(_last_retrain_path())
    except OSError:
        return {}
    if _refusal_cache["mtime"] != mtime:
        result = last_retrain() or {}
        _refusal_cache["data"] = {
            m["key"]: (m.get("message"), result.get("finished_at"))
            for m in result.get("models", []) if m.get("state") == "refused" and m.get("message")
        }
        _refusal_cache["mtime"] = mtime
    return _refusal_cache["data"]


def model_status(device_id, node_type) -> dict:
    """
    The model state for one machine, for the device read and the dashboard.

    Returns a dict with exactly these keys:
      state                  "ready" (a model scores this machine), "learning" (not enough clean readings yet, so it
                             is not scored and cannot raise an anomaly alert), "legacy" (a bundle saved by an earlier
                             version, which scores nothing until a retrain), "none" (no model scores this machine: no
                             file or its model was refused or withdrawn and reason says which) or "error" (the model
                             file will not load)
      scope                  "machine" (its own model), "node_type" (its node type's model), "general" or None
      hours_collected        hours of clean readings gathered as of the last training (None when unknown)
      hours_needed           the hours of clean readings a model of its own needs (120 at a 5 s interval: the test part
                             alone must hold a day) or None
      false_alerts_per_week  the false anomaly alerts per machine per week on the newest held-back readings (the test
                             part, which nothing was tuned on) for the model in use and
      false_alerts_per_week_high_95  its 95 per cent upper bound, which is what a figure from a few days can promise
      trained_at             ISO 8601 time the bundle was trained (None when unknown)
      refusal                the message of the last retrain when it refused this machine's own model, else None
      refused_at             ISO 8601 time of that retrain, else None
      monitored              True when a model scores this machine. False is a machine the model is not watching
      reason                 why it is not monitored or what it is monitored by, in words. None when there is nothing to say
      ambient                how the machine's own model uses the room (its ambient reference or the lack of one)
      light                  True when its own model is a light one (no forest, beyond the cap on full models)

    It never touches the database: it reads the loaded bundle and the last retrain's file, so it is cheap enough for a
    list of machines.
    """
    status = _model_status(device_id, node_type)
    refused = _refusals().get(f"machine:{device_id}")
    if refused is not None:
        status = {**status, "refusal": refused[0], "refused_at": refused[1]}
    return status


def machine_report() -> list[dict]:
    """One line per machine the last training saw, for GET /ml/status: its model, the hours and the reason for it."""
    meta = _meta()
    rows = []
    for device_id, info in (meta.get("machines") or {}).items():
        status = model_status(device_id, info.get("node_type"))
        reason = status["reason"]
        if status["refusal"] and not status["monitored"]:
            reason = status["refusal"]
        rows.append({
            "device_id": device_id, "state": status["state"], "scope": status["scope"], "over_cap": bool(info.get("over_cap")),
            "light": status["light"], "monitored": status["monitored"], "hours_collected": status["hours_collected"],
            "hours_needed": status["hours_needed"], "reason": reason, "ambient": status["ambient"],
            "interval_s": info.get("interval_s"), "recorded_interval_s": info.get("recorded_interval_s"),
        })
    return sorted(rows, key=lambda r: r["device_id"])


def bundle_summary() -> dict:
    """What is in service, for GET /ml/status: the state, when it was trained, one line per model and per machine."""
    state = model_state()
    out = {"state": state, "trained_at": None, "models": [], "last_retrain": last_retrain(), "machines": [],
           "max_machine_models": MAX_MACHINE_MODELS, "monitored_machines": 0, "unmonitored_machines": 0}
    if state in ("none", "error") or _model is None:
        return out
    meta = _meta()
    out["trained_at"] = meta.get("trained_at")
    out["machines"] = machine_report()
    out["monitored_machines"] = sum(1 for r in out["machines"] if r["monitored"])
    out["unmonitored_machines"] = sum(1 for r in out["machines"] if not r["monitored"])
    for key, model in ((k, m) for k, m in (_model.items() if isinstance(_model, dict) else [("default", _model)]) if k != META_KEY):
        record = _record_of(model)
        detector = getattr(model, "phaemos_detector", None)
        out["models"].append({
            "key": key, "scope": "machine" if key.startswith("machine:") else ("general" if key == "default" else "node_type"),
            "legacy": (getattr(model, "phaemos_schema", None) or 0) < SCHEMA_VERSION,
            "light": not _has_forest(model),
            "false_alerts_per_week": record.get("false_alerts_per_week"),
            "false_alerts_per_week_high_95": record.get("false_alerts_per_week_high_95"),
            "features": getattr(model, "phaemos_features", None),
            "detector": None if detector is None else {"boundary": round(float(detector.boundary), 2),
                                                       **(detector.extra.get("arl") or {})},
            "trained_at": getattr(model, "phaemos_trained_at", None),
        })
    return out


# -- scoring one reading ----------------------------------------------------------------------------------------------

def _candidates(reading: dict, device_id=None) -> list[tuple[str, object]]:
    """The models that may score this reading, in the order to try: the machine's own, its node type's, the general one."""
    if _model is None:
        return []
    if not isinstance(_model, dict):
        # a single model saved by an earlier version
        return [("default", _model)]
    found = []
    node = reading.get("node_type") or ""
    if device_id is not None and f"machine:{device_id}" in _model:
        found.append((f"machine:{device_id}", _model[f"machine:{device_id}"]))
    if node and _model.get(node) is not None:
        found.append((node, _model[node]))
    # a node type that is still learning is not handed to the general model, which never saw it
    if _model.get("default") is not None and node not in (_meta().get("learning_node_types") or {}):
        found.append(("default", _model["default"]))
    return found


def _features(model) -> list[str]:
    return getattr(model, "phaemos_features", FEATURE_COLS)


def missing_features(reading: dict, device_id=None) -> list[str]:
    """
    The model inputs a reading lacks, when no model can score it. Empty when one can or when there is no model.

    It names the columns of the first model that applies (the machine's own, then the node type's, else the general
    one), which is the one an operator would expect to score the node.
    """
    candidates = _candidates(reading, device_id)
    if not candidates or any(_has_all(reading, _features(m)) for _, m in candidates):
        return []
    return [c for c in _features(candidates[0][1]) if reading.get(c) is None]


def used_general_fallback(reading: dict) -> bool:
    """
    True when a model more specific than the general one exists for the reading, cannot score it and the general
    model did. It answers for the reading last passed to score_reading in this thread when it is the same object.
    """
    scored = getattr(_local, "scored", None)
    if scored is not None and scored[0] is reading:
        return scored[1] == "default" and scored[2]
    candidates = _candidates(reading)
    if len(candidates) < 2:
        return False
    first = next((k for k, m in candidates if _has_all(reading, _features(m))), None)
    return first == "default"


# the per-machine state of the change detector and the slow levels. The default is process memory. The server replaces
# it with a store backed by the database (anything with get(key) and put(key, state) and optionally paused(key, t)),
# see change_detector.MemoryStateStore and services/detector_store.py
_state_store = cd.MemoryStateStore()


def set_state_store(store) -> None:
    global _state_store
    _state_store = store


def state_store():
    return _state_store


def _machine_state(model, device_id) -> cd.DetectorState:
    """The stored state of this machine for this model: carried over from the model before a retrain when it can be."""
    state = _state_store.get(str(device_id))
    width = len(_features(model))
    if state is None:
        return _fresh_state(model)
    if state.model_id != _model_id(model):
        # a retrain: carry what is still valid, start cold only when nothing can be carried
        return carry_state(state, model) or _fresh_state(model)
    if state.smooth is not None and state.smooth.shape[-1] != width:
        return _fresh_state(model)
    return state


def _ambient_reference(device_id, t: float) -> float | None:
    """The machine's site reference at time t from the state store (the database in the server) or None."""
    look = getattr(_state_store, "ambient", None)
    if look is None:
        return None
    try:
        value = look(str(device_id), t)
        return None if value is None else float(value)
    except Exception:  # noqa: BLE001
        return None


def _paused(device_id, t: float) -> bool:
    check = getattr(_state_store, "paused", None)
    if check is None:
        return False
    try:
        return bool(check(str(device_id), t))
    except Exception:  # noqa: BLE001
        return False


def explain_reading(reading: dict, device_id=None) -> dict | None:
    """
    Which sensor made a reading's score high, for the alert's reason. The reading is a dict of the stored columns.

    Returns a dict for decide's `details` argument or None when the reading is under the boundary or nothing can score
    it. Three shapes:
      {"sensor", "value", "direction", "low", "high", "deviations"}  a value outside the machine's usual range
      {"kind": "drift", "sensor", "value", "expected", "offset", "direction", "minutes"}  a change that built up over time
      {"kind": "combination", "sensor", "value", "low", "high", "direction"}  the forest carried the score: the
          combination is unusual and the sensor named is the one furthest from its usual range
    The detector's answer comes from the machine's stored state as the last scored reading left it, so call this straight
    after that reading was scored. It never steps anything.
    """
    try:
        _load_model()
        for _, model in _candidates(reading, device_id):
            cols = _features(model)
            if td.AMBIENT_REF in cols and reading.get(td.AMBIENT_REF) is None and device_id is not None:
                when = reading.get("recorded_at")
                moment = when.timestamp() if hasattr(when, "timestamp") else time.time()
                reading = {**reading, td.AMBIENT_REF: _ambient_reference(device_id, moment)}
            if not _has_all(reading, cols):
                continue
            x = _matrix([reading], cols)
            xd = _derived(model, x)
            state = _machine_state(model, device_id) if device_id is not None else _fresh_state(model)
            baseline = getattr(model, "phaemos_baseline", None)
            level = np.zeros(len(cols))
            if baseline is not None and state.base_level is not None and baseline.level_bound is not None \
                    and state.base_level.shape == baseline.level_bound.shape:
                level = state.base_level[int(bl.state_of(baseline, xd)[0])]
            adjusted = xd - level
            forest = float(normalise(model, _forest_raw(model, adjusted))[0]) if _has_forest(model) else 0.0
            base = 0.0 if baseline is None else float(bl.normalise(baseline, bl.raw_scores(baseline, adjusted))[0])
            detector = getattr(model, "phaemos_detector", None)
            drift = 0.0
            if detector is not None and state.s_pos is not None and state.last_t is not None:
                drift = float(cd.normalise(detector, np.array([max(state.s_pos.max(), state.s_neg.max())]))[0])
            best = max(forest, base, drift)
            if best < ANOMALY_THRESHOLD:
                return None
            if drift >= max(forest, base):
                note = cd.explain(detector, state, xd[0], state.last_t)
                return _undo_rise(model, note, x[0], xd[0])
            if baseline is None:
                return None
            note = bl.explain(baseline, adjusted[0])
            j = cols.index(note["sensor"])
            # the range is stated in the reading's own terms: the slow level is added back to it
            note = {**note, "value": round(float(xd[0, j]), 4), "low": round(note["low"] + level[j], 4),
                    "high": round(note["high"] + level[j], 4)}
            if forest > base:
                note["kind"] = "combination"
            return _undo_rise(model, note, x[0], xd[0])
    except Exception:
        return None
    return None


def _undo_rise(model, note: dict, x: np.ndarray, xd: np.ndarray) -> dict:
    """A note about a rise above the air says so, so the reason never states a rise as if it were the temperature."""
    plan = getattr(model, "phaemos_ambient", None)
    if plan and note.get("sensor") in plan["rise"]:
        note = {**note, "rise_above": plan["air"]}
    return note


def score_reading(reading: dict, device_id=None, at=None, track: bool = True) -> tuple[float | None, bool]:
    """
    Score a single telemetry reading.
    Returns (anomaly_score: float 0-1 or None, is_anomaly: bool).

    The machine's own model scores it when it has one and the reading has every column that model needs. Otherwise
    its node type's model does and failing that the general model. The score is None and is_anomaly False only when
    none can or when no model applies. Such a reading is neither normal nor anomalous and scoring_problem says why.

    device_id is the machine the reading came from. Without it only the node type's and the general models apply and no
    state is kept. at is the time of the reading (the stored recorded_at, default now): the detector accumulates over the
    readings' own times, so a batch stamped at one instant adds nothing and a retried transaction cannot step it twice.
    track=False leaves the state alone, for a manual test score. A reading inside a maintenance window (the store's
    paused) is scored without stepping and the detector restarts after the window.
    Scoring one reading with the detector cost about half a millisecond on a loaded developer machine (see docs/architecture.md).
    """
    global _problem
    _local.scored = None
    _note_reading_problem(None)
    try:
        _load_model()
        _maybe_reload()
    except Exception as exc:  # noqa: BLE001
        _problem = f"the model file could not be loaded ({type(exc).__name__})"
        _log_once(_problem)
        return None, False
    if _model is None:
        # no file at all is the safe pass-through. A file that will not load is a problem, so nothing is scored
        return (None, False) if _problem else (0.0, False)
    if isinstance(_model, dict) and _is_old(_model):
        _note_reading_problem("the model file was saved by an earlier version and scores nothing until a retrain")
        return None, False
    original = reading
    candidates = _candidates(reading, device_id)
    if not candidates:
        reason = (_meta().get("unmonitored") or {}).get(str(device_id)) if device_id is not None else None
        _note_reading_problem("no model is in service for this machine" + (f": {reason}" if reason else ""))
        return None, False
    for index, (key, model) in enumerate(candidates):
        cols = _features(model)
        if td.AMBIENT_REF in cols and reading.get(td.AMBIENT_REF) is None and device_id is not None:
            # the site's reference is not in the reading: it is the latest reading of the machine's ambient source
            moment = at.timestamp() if at is not None else time.time()
            reading = {**reading, td.AMBIENT_REF: _ambient_reference(device_id, moment)}
        if not _has_all(reading, cols):
            continue
        try:
            x = _matrix([reading], cols)[0]
            own = key.startswith("machine:") and device_id is not None
            if own and track:
                moment = at.timestamp() if at is not None else time.time()
                state = _machine_state(model, device_id)
                if _paused(device_id, moment):
                    forest, base = score_parts(model, x[None])
                    normalised = float(max(forest[0], 0.0 if base is None else base[0]))
                    _pause(state)
                else:
                    normalised, _ = score_step(model, state, moment, x)
                _state_store.put(str(device_id), state)
            elif own:
                # a manual score reads the levels the machine has reached and changes nothing
                state = _machine_state(model, device_id)
                parts = sequence_parts(model, np.array([time.time()]), x[None], state=cd.DetectorState(
                    base_level=None if state.base_level is None else state.base_level.copy(), model_id=state.model_id))
                normalised = float(combine(model, parts)[0])
            else:
                forest, base = score_parts(model, x[None])
                normalised = float(forest[0] if base is None else max(forest[0], base[0]))
        except Exception as exc:  # noqa: BLE001
            # one machine's failure is that reading's problem: it is stored unscored with the reason and the fleet's model
            # state is untouched. The machine's state is dropped so its next reading starts fresh
            _note_reading_problem(f"scoring failed ({type(exc).__name__})")
            _log_once(f"scoring failed for a reading ({type(exc).__name__})")
            if device_id is not None and track:
                try:
                    _state_store.put(str(device_id), _fresh_state(model))
                except Exception:  # noqa: BLE001
                    pass
            return None, False
        _local.scored = (original, key, index > 0)
        # round to 4 decimal places to keep API responses clean without losing meaningful precision
        return round(normalised, 4), normalised >= ANOMALY_THRESHOLD
    return None, False


def reload_model() -> None:
    """Force a fresh load of model.pkl from disk. Called after retraining."""
    global _model, _problem, _load_failure, _loaded_mtime, _generation
    # reset to None first so _load_model re-reads the file even if one was already loaded.
    _model, _problem, _load_failure, _loaded_mtime = None, None, None, None
    _generation += 1
    _packed.clear()
    _logged.clear()
    _load_model()

