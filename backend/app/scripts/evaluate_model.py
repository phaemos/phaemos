"""
An honest evaluation of the anomaly model on simulated machines. Run it with `make ml-eval`.

NOTHING HERE HAS SEEN A REAL MACHINE. The data is simulated. It shows whether the design behaves on data that is
deliberately untidy and it cannot show how a real plant behaves. A real machine has failure modes nobody simulated
here and its normal behaviour drifts in ways a generator does not.

What the simulated machines contain and what each part stands for (all of it is healthy unless said otherwise):

- a daily cycle: the room warms by day and cools by night, light follows the sun. Stands for the building.
- ordinary sensor noise: correlated from one reading to the next like a real sensor, larger when running.
- slow seasonal drift: a slow swing of the room temperature over weeks. Stands for weather and heating.
- slow weather: pressure and humidity wander over days.
- load changes: the machine switches between idle and running on shifts with a lunch break and stoppages. Vibration
  and current and heat follow the load. This is healthy and is the classic cause of false alarms.
- short harmless excursions: a door opening warms the node for a minute. A forklift passes and the vibration bumps. The
  sound spikes. A few a day. These are the readings a run of three in a row mistakes for a fault.
- missing readings: single posts lost at random and whole gaps of minutes (a bad radio link). Also a sensor that drops
  out for a few minutes, which gives readings that lack a column.
- different posting intervals: 5 s and 10 s and 30 s and 60 s machines.
- in the training fortnight only: a maintenance window with abnormal readings and a misbehaving spell with a machine
  alert open. They are labelled as the real system would label them, so training must leave them out.

Then labelled faults are injected into the healthy test week, see services/model_evaluation.py.

Three set-ups are compared on the same seven healthy days:

  OLD, as deployed   the model fitted at contamination 0.05 on the newest 10,000 rows of the whole table, the way
                     routes/ml.py did. The alert rule was three anomalous readings in a row.
  OLD, good data     the same old model and rule, but fitted on 10,000 rows spread evenly over the same fortnight.
                     This separates the cost of the old rule and the 5 per cent boundary from the cost of the old
                     way of choosing training rows.
  NEW                the measured boundary, the clean training rows and the sustained-window decision.
"""
import argparse
import io
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import joblib
import numpy as np
from scipy.signal import lfilter
from sklearn.ensemble import IsolationForest

# the evaluation needs no database and no secret. The settings object still insists on a few values, so stand-ins are
# set when the environment has none. They are placeholders and are never used for anything
os.environ.setdefault("SECRET_KEY", "evaluation-only-placeholder")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:placeholder@localhost:5432/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from app.services import ml_service as ml  # noqa: E402
from app.services import model_evaluation as ev  # noqa: E402
from app.services import training_data as td  # noqa: E402

COLS = td.MODEL_COLS
DAY = 86_400.0
# a Monday at midnight, so the weekly shape of the load is the same whatever day this is run
START = datetime(2026, 3, 2, tzinfo=timezone.utc).timestamp()
TRAIN_DAYS = 14
TEST_DAYS = 7
SEED = 20260302


@dataclass
class Spec:
    name: str
    node_type: str
    interval_s: int
    cols: tuple


ESP = ("temperature", "humidity", "pressure", "vibration_x", "vibration_y", "vibration_z", "bus_voltage", "current_ma",
       "power_mw", "sound_level", "light_level")
STM = ("vibration_x", "vibration_y", "vibration_z", "gyro_x", "gyro_y", "gyro_z", "fft_peak_hz", "vib_magnitude")
PICO = ("temperature", "humidity", "pressure", "light_level")
FLEET = [
    Spec("press-01", "esp32", 5, ESP),
    Spec("press-02", "esp32", 5, ESP),
    Spec("pump-01", "esp32", 10, ESP),
    Spec("fan-01", "stm32", 5, STM),
    Spec("room-01", "pico_w", 30, PICO),
    Spec("room-02", "pico_w", 60, PICO),
]
# an ESP32 hub that also carries its contact probe and its infrared sensor on the machine, as the real hub can: the
# machine temperature beside an air temperature, which is the ambient reference
ESPS = ESP + ("contact_temp", "ir_temperature")
# the fleet of the full evaluation: the six above and two machines with an ambient reference
FULL_FLEET = FLEET + [
    Spec("mill-01", "esp32", 5, ESPS),
    Spec("mill-02", "esp32", 10, ESPS),
]
# seeds, from one manifest (evaluation_seeds.json). The tuning (--tune, which chose ALLOWANCE and the level settings of the
# change detector) reads VALIDATION_SEEDS and refuses a test seed. The reported figures are from TEST_SEEDS
SEED_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluation_seeds.json")


def seed_manifest() -> dict:
    import json
    with open(SEED_MANIFEST) as handle:
        data = json.load(handle)
    if set(data["validation"]) & set(data["test"]):
        raise ValueError("a seed is in both the validation and the test list of the seed manifest")
    return data


VALIDATION_SEEDS = tuple(seed_manifest()["validation"])
TEST_SEEDS = tuple(seed_manifest()["test"])


@dataclass
class Sim:
    spec: Spec
    index: int
    times: np.ndarray
    X: np.ndarray
    reasons: np.ndarray


def _ar(rng, n, interval, tau, sd):
    """Noise that carries from one reading to the next, as a real sensor's does. tau is its memory in seconds."""
    phi = np.exp(-interval / tau)
    return lfilter([1.0], [1.0, -phi], rng.normal(0.0, sd * np.sqrt(1.0 - phi ** 2), n))


def _lag(x, interval, tau):
    alpha = 1.0 - np.exp(-interval / tau)
    return lfilter([alpha], [1.0, -(1.0 - alpha)], x)


def _load(rng, n, interval, days):
    """Idle and running by shift: weekdays two blocks with a lunch break and stoppages, some Saturdays and no Sundays."""
    target = np.full(n, 0.1)
    for day in range(days):
        blocks = []
        dow = day % 7
        if dow < 5:
            blocks = [(6.0 + rng.uniform(-0.6, 0.6), 12.0 + rng.uniform(-0.3, 0.3)),
                      (12.75 + rng.uniform(-0.3, 0.3), 22.0 + rng.uniform(-0.7, 0.7))]
        elif dow == 5 and rng.random() < 0.5:
            start = 8.0 + rng.uniform(-1, 1)
            blocks = [(start, start + rng.uniform(3.0, 7.0))]
        for h0, h1 in blocks:
            i0, i1 = int((day * DAY + h0 * 3600) / interval), int((day * DAY + h1 * 3600) / interval)
            target[i0:i1] = rng.uniform(0.85, 1.0)
            # stoppages inside a running block: a jam or a changeover
            for _ in range(rng.integers(0, 3)):
                s = rng.integers(i0, max(i1 - 1, i0 + 1))
                target[s:s + int(rng.uniform(8, 35) * 60 / interval)] = 0.1
    return np.clip(_lag(target, interval, 120.0), 0.05, 1.0)


def simulate(spec: Spec, index: int, days: int, seed: int = SEED, knobs: dict | None = None) -> Sim:
    """
    One simulated machine. With no knobs it is the same machine on the same seed as every earlier version.

    knobs change the test days only (after TRAIN_DAYS) unless their name says otherwise, so a regime change after training
    can be measured: ambient_test (degrees added to the room), season_ramp (degrees a day added from the first test day),
    load_scale (the running load scaled, a lighter or heavier product), always_on (a third shift: running all day),
    temp_noise_test and temp_noise_all (temperature noise multiplied), free_humidity (humidity no longer follows the room,
    from the start, so it applies to training too), site_reference (a room node in the same place is the machine's
    ambient source, all along).
    """
    k = knobs or {}
    rng = np.random.default_rng(seed + 101 * index)
    interval = spec.interval_s
    n = int(days * DAY / interval)
    sec = np.arange(n) * float(interval)
    hour = (sec / 3600.0) % 24.0
    load = _load(rng, n, interval, days)
    test = sec >= TRAIN_DAYS * DAY
    if k.get("load_scale"):
        load = np.where(test, 0.05 + (load - 0.05) * k["load_scale"], load)
    if k.get("always_on"):
        load = np.where(test, np.clip(np.maximum(load, 0.9), 0.05, 1.0), load)
    heat = _lag(load, interval, 1500.0)
    # per-machine character, so no two machines are the same
    persona = rng.uniform(0.92, 1.08, 6)
    # the room: a daily cycle and a slow seasonal swing and weather that changes day to day
    daily = 2.0 * np.sin(2 * np.pi * (hour - 9.0) / 24.0)
    seasonal = 1.0 * np.sin(2 * np.pi * (sec / DAY) / 90.0 + index)
    weather_days = rng.normal(0, 0.7, days + 2)
    weather = np.interp(sec / DAY, np.arange(days + 2) + 0.5, weather_days)
    ambient = 21.0 + daily + seasonal + weather
    if k.get("ambient_test"):
        ambient = ambient + np.where(test, k["ambient_test"], 0.0)
    if k.get("season_ramp"):
        ambient = ambient + np.where(test, (sec / DAY - TRAIN_DAYS) * k["season_ramp"], 0.0)
    daylight = np.clip(np.sin(np.pi * (hour - 6.0) / 14.0), 0.0, 1.0)
    v = {}
    tnoise = _ar(rng, n, interval, 60.0, 0.25)
    if k.get("temp_noise_test"):
        tnoise = np.where(test, tnoise * k["temp_noise_test"], tnoise)
    if k.get("temp_noise_all"):
        tnoise = tnoise * k["temp_noise_all"]
    # a node with a machine temperature (SURFACE) carries its BME280 away from the heat: its air temperature is the room
    # with a little of the machine's warmth. A node without one has its only temperature sensor on the machine
    air_heat = 0.6 if any(c in spec.cols for c in ("contact_temp", "ir_temperature")) else 7.0
    v["temperature"] = ambient + air_heat * persona[0] * heat + tnoise
    hnoise = _ar(rng, n, interval, 90.0, 0.8)
    if k.get("free_humidity"):
        rng2 = np.random.default_rng(seed + 7 + index)
        grid = np.arange(0, days + 2, 0.25)
        wander = np.interp(sec / DAY, grid, rng2.normal(0, 4.0, len(grid)))
        v["humidity"] = 55.0 + wander - 2.0 * heat + hnoise
    else:
        v["humidity"] = 55.0 - 1.5 * (ambient - 21.0) - 2.0 * heat + 2.0 * weather + hnoise
    v["pressure"] = 1013.0 + 4.0 * np.interp(sec / DAY, np.arange(days + 2) + 0.5, rng.normal(0, 1, days + 2)) + _ar(rng, n, interval, 300.0, 0.3)
    v["vibration_x"] = 0.03 + 0.09 * persona[1] * load + _ar(rng, n, interval, 20.0, 0.008) * (0.5 + load)
    v["vibration_y"] = 0.03 + 0.08 * persona[2] * load + _ar(rng, n, interval, 20.0, 0.008) * (0.5 + load)
    v["vibration_z"] = 1.0 + 0.01 * load + _ar(rng, n, interval, 20.0, 0.008)
    current = 120.0 + 300.0 * persona[3] * load + _ar(rng, n, interval, 30.0, 6.0) * (0.6 + load)
    v["current_ma"] = current
    v["bus_voltage"] = 5.0 - 0.02 * load + _ar(rng, n, interval, 60.0, 0.015)
    v["power_mw"] = v["bus_voltage"] * current
    v["sound_level"] = 38.0 + 16.0 * persona[4] * load + _ar(rng, n, interval, 15.0, 1.5)
    v["light_level"] = 80.0 + 520.0 * daylight + 120.0 * (load > 0.5) + _ar(rng, n, interval, 120.0, 20.0)
    v["gyro_x"] = _ar(rng, n, interval, 10.0, 0.2 + 0.9 * load.mean()) * (0.4 + load)
    v["gyro_y"] = _ar(rng, n, interval, 10.0, 0.2 + 0.9 * load.mean()) * (0.4 + load)
    v["gyro_z"] = _ar(rng, n, interval, 10.0, 0.2 + 0.9 * load.mean()) * (0.4 + load)
    v["fft_peak_hz"] = 22.0 + 2.4 * persona[5] * load + _ar(rng, n, interval, 20.0, 0.15)
    v["vib_magnitude"] = np.abs(0.04 + 0.12 * load + _ar(rng, n, interval, 20.0, 0.012))
    if any(c in spec.cols for c in ("contact_temp", "ir_temperature")):
        # the machine's own temperatures, from a generator of their own so every other channel is drawn as before
        rng3 = np.random.default_rng(seed + 31 + 101 * index)
        v["contact_temp"] = ambient + 9.0 * persona[0] * heat + _ar(rng3, n, interval, 60.0, 0.15)
        v["ir_temperature"] = ambient + 11.0 * persona[0] * heat + _ar(rng3, n, interval, 30.0, 0.4)
    X = np.full((n, len(COLS)), np.nan)
    for c in spec.cols:
        X[:, COLS.index(c)] = v[c]
    if k.get("site_reference"):
        # a room node in the same place set as this machine's ambient source: the room's air with a little noise of its own
        # and none of the machine's heat. From a generator of its own so every other channel is drawn as before
        rng4 = np.random.default_rng(seed + 53 + 101 * index)
        X[:, COLS.index(td.AMBIENT_REF)] = ambient + _ar(rng4, n, interval, 120.0, 0.15)
    col = {c: COLS.index(c) for c in spec.cols}
    # short harmless excursions, about two a day: stand for a door and a forklift and a loud neighbour
    for _ in range(rng.poisson(2.0 * days)):
        i = rng.integers(0, n - 1)
        length = max(int(rng.uniform(15, 90) / interval), 1)
        kind = rng.integers(0, 3)
        if kind == 0 and "temperature" in col:
            X[i:i + length, col["temperature"]] += rng.uniform(1.2, 2.0)
        elif kind == 1 and "vibration_x" in col:
            X[i:i + length, col["vibration_x"]] *= rng.uniform(1.8, 2.5)
        elif "sound_level" in col:
            X[i:i + length, col["sound_level"]] += 10.0
    reasons = np.full(n, "", dtype=object)
    # labelled trouble in the training fortnight only
    if days > TRAIN_DAYS:
        a, b = int(3.3 * DAY / interval), int(3.5 * DAY / interval)
        for c in ("vibration_x", "vibration_y", "vib_magnitude"):
            if c in col:
                X[a:b, col[c]] *= 3.0
        if "temperature" in col:
            X[a:b, col["temperature"]] += rng.normal(0, 3.0, b - a).cumsum() * 0.02
        reasons[a:b] = "maintenance"
        if index in (0, 3):
            a, b = int(13.55 * DAY / interval), int(13.9 * DAY / interval)
            for c in ("vibration_x", "vibration_y", "vib_magnitude"):
                if c in col:
                    X[a:b, col[c]] *= 2.2
            if "temperature" in col:
                X[a:b, col["temperature"]] += 3.0
            # the alert opens ten minutes in. The first ten minutes look clean, as they would in the database
            reasons[a + int(600 / interval):b] = "machine_alert"
    # a sensor drops out for a few minutes about every other day
    for _ in range(int(days / 2)):
        c = "humidity" if "humidity" in col else ("sound_level" if "sound_level" in col else "vibration_z")
        if c not in col:
            continue
        a = rng.integers(0, n - 1)
        b = a + int(rng.uniform(300, 1200) / interval)
        X[a:b, col[c]] = np.nan
        reasons[a:b] = np.where(reasons[a:b] == "", "sensor_fault", reasons[a:b])
    t = START + sec + rng.normal(0, 0.03 * interval, n).clip(-0.2 * interval, 0.2 * interval)
    keep = rng.random(n) > 0.007
    # link gaps of one to eight minutes about daily
    for _ in range(days):
        a = rng.integers(0, n - 1)
        keep[a:a + int(rng.uniform(60, 480) / interval) + 1] = False
    t, X, reasons = t[keep], X[keep], reasons[keep]
    # a reading next to a gap longer than the late limit is labelled the way the SQL labels it
    gap = np.diff(t, prepend=t[0] - interval, append=t[-1] + interval)
    late = td.LATE_GAP_INTERVALS * interval
    near = (gap[:-1] > late) | (gap[1:] > late)
    reasons = np.where((reasons == "") & near, "link", reasons)
    return Sim(spec, index, t, X, reasons)


def simulate_fleet(days: int = TRAIN_DAYS + TEST_DAYS, fleet=None, seed: int = SEED, knobs: dict | None = None) -> list[Sim]:
    return [simulate(s, i, days, seed, knobs) for i, s in enumerate(fleet or FLEET)]


# -- the old model and the old rule, copied from before this change ------------------------------------------------

OLD_THRESHOLD = 0.7
OLD_RUN = 3
OLD_RUN_WINDOW = 60.0
OLD_CONTAMINATION = 0.05
OLD_ROWS = 10_000
OLD_MIN_ROWS = 50
OLD_PRESENCE = 0.9


class OldBundle:
    """The model of routes/ml.py and ml_service.py before this change: contamination 0.05 and no column scaling."""

    def __init__(self, X: np.ndarray, node_types: np.ndarray):
        self.models = {}
        have = (~np.isnan(X)).sum(axis=0)
        general = [i for i in range(X.shape[1]) if have[i] >= OLD_PRESENCE * len(X)]
        if not general and have.max() > 0:
            general = [int(have.argmax())]
        self._fit("default", X, general)
        for node in sorted(set(node_types)):
            rows = X[node_types == node]
            if len(rows) < OLD_MIN_ROWS:
                continue
            present = (~np.isnan(rows)).sum(axis=0)
            self._fit(node, rows, [i for i in range(X.shape[1]) if present[i] >= OLD_PRESENCE * len(rows)])

    def _fit(self, key, rows, idx):
        if not idx:
            return
        part = rows[:, idx]
        part = part[~np.isnan(part).any(axis=1)]
        if len(part) < OLD_MIN_ROWS:
            return
        model = IsolationForest(n_estimators=200, contamination=OLD_CONTAMINATION, random_state=42)
        model.fit(part)
        decisions = model.score_samples(part) - model.offset_
        self.models[key] = (model, idx, float(max(np.median(decisions), 1e-6)))

    def score(self, node: str, X: np.ndarray) -> np.ndarray:
        """Normalised scores by the node type's model and the general one for what that cannot score. NaN when neither can."""
        out = np.full(len(X), np.nan)
        for key in (node, "default"):
            if key not in self.models:
                continue
            model, idx, typical = self.models[key]
            part = X[:, idx]
            todo = np.isnan(out) & ~np.isnan(part).any(axis=1)
            if todo.any():
                dec = ml.raw_scores(model, part[todo]) - model.offset_
                out[todo] = np.clip(OLD_THRESHOLD * (typical - dec) / typical, 0.0, 1.0)
        return out


def old_replay(times, scores, interval_s):
    """
    The old alert rule, from evaluate_anomaly before this change. An alert opens when the last three scored readings
    from the last window are all anomalous and none is open. It resolves when the last three are all normal.
    """
    keep = ~np.isnan(scores)
    t, anomalous = times[keep], scores[keep] >= OLD_THRESHOLD
    window = max(OLD_RUN_WINDOW, 2.0 * OLD_RUN * max(interval_s, 1.0))
    out = ev.Replay()
    is_open = False
    for i in range(OLD_RUN - 1, len(t)):
        if t[i] - t[i - OLD_RUN + 1] > window:
            continue
        trio = anomalous[i - OLD_RUN + 1:i + 1]
        if not trio.any():
            is_open = False
        elif trio.all() and not is_open:
            is_open = True
            out.raises.append({"index": i, "time": float(t[i]), "severity": "warning"})
    return out


# -- the comparison -----------------------------------------------------------------------------------------------

def _split(sim: Sim):
    cut = START + TRAIN_DAYS * DAY
    train = sim.times < cut
    return train, ~train


def train_new(sims: list[Sim]):
    """Train the new bundle on the training fortnight, with the selection of services/training_data.py."""
    datas = []
    for s in sims:
        train, _ = _split(s)
        datas.append(td.select_from_arrays(
            s.times[train], s.X[train], s.reasons[train], s.spec.interval_s, device_id=s.spec.name,
            name=s.spec.name, node_type=s.spec.node_type,
        ))
    counts: dict = {}
    for s in sims:
        counts[s.spec.node_type] = counts.get(s.spec.node_type, 0) + 1
    return ml.train_bundle(datas, counts, len(sims)), datas


def old_bundles(sims: list[Sim]):
    """The two old set-ups: the newest 10,000 rows of the table and 10,000 rows spread over the fortnight."""
    times = np.concatenate([s.times[_split(s)[0]] for s in sims])
    X = np.vstack([s.X[_split(s)[0]] for s in sims])
    nodes = np.concatenate([np.full(int(_split(s)[0].sum()), s.spec.node_type) for s in sims])
    order = np.argsort(times)
    times, X, nodes = times[order], X[order], nodes[order]
    newest = slice(len(times) - OLD_ROWS, None)
    deployed = OldBundle(X[newest], nodes[newest])
    even = np.linspace(0, len(times) - 1, OLD_ROWS).round().astype(int)
    good = OldBundle(X[even], nodes[even])
    return deployed, good


def new_scores(bundle: dict, sim: Sim, X: np.ndarray, t: np.ndarray):
    """Normalised scores of the new bundle for X (a machine's rows) and the key of the model that scored them."""
    previous = ml._model
    ml._model = bundle
    try:
        key, model = None, None
        for k, m in ml._candidates({"node_type": sim.spec.node_type}, sim.spec.name):
            if all(c in sim.spec.cols or c == td.AMBIENT_REF for c in m.phaemos_features):
                key, model = k, m
                break
        if model is None:
            return np.full(len(X), np.nan), None, None
        idx = [COLS.index(c) for c in model.phaemos_features]
        part = X[:, idx]
        out = np.full(len(X), np.nan)
        ok = ~np.isnan(part).any(axis=1)
        out[ok] = ml.score_matrix(model, part[ok], None, t[ok], sim.spec.interval_s)
        return out, key, model
    finally:
        ml._model = previous


def evaluate(fleet=None, seed: int = SEED) -> dict:
    sims = simulate_fleet(fleet=fleet, seed=seed)
    started = time.time()
    outcome, datas = train_new(sims)
    train_s = time.time() - started
    if outcome.bundle is None:
        raise SystemExit("the new model was refused on the simulated fortnight: " + outcome.summary)
    deployed, good = old_bundles(sims)
    rows = []
    weeks = TEST_DAYS / 7.0
    for s in sims:
        _, test = _split(s)
        t, X = s.times[test], s.X[test]
        scores_new, key, model = new_scores(outcome.bundle, s, X, t)
        if key is None:
            scope, alerts_new = "none", None
        else:
            scope = "machine" if key.startswith("machine:") else ("node type" if key == s.spec.node_type else "general")
            scored = ~np.isnan(scores_new)
            alerts_new = len(ev.replay(t[scored], scores_new[scored], s.spec.interval_s).raises) / weeks
        row = {"name": s.spec.name, "node": s.spec.node_type, "interval": s.spec.interval_s, "scope": scope,
               "new": alerts_new}
        for label, bundle in (("old_deployed", deployed), ("old_good", good)):
            sc = bundle.score(s.spec.node_type, X)
            row[label] = len(old_replay(t, sc, s.spec.interval_s).raises) / weeks
        rows.append(row)
    # the labelled faults, injected into the healthy test week of each machine
    kinds = list(ev.FAULT_KINDS)
    faults = {k: {"old": [0, 0, []], "new": [0, 0, []]} for k in kinds}
    for s in sims:
        _, test = _split(s)
        t, X = s.times[test], s.X[test]
        scores_new, key, model = new_scores(outcome.bundle, s, X, t)
        if model is None:
            continue
        cols = list(model.phaemos_features)
        idx = [COLS.index(c) for c in cols]
        ok = ~np.isnan(X[:, idx]).any(axis=1)
        seg = ev.Segment(s.spec.name, s.spec.interval_s, t[ok], X[ok][:, idx])
        found = ev.detection([seg], cols, lambda Z, t, i, m=model: ml.score_matrix(m, Z, None, t, i))
        for f in found["faults"]:
            faults[f["kind"]]["new"][0] += f["trials"]
            faults[f["kind"]]["new"][1] += f["caught"]
            faults[f["kind"]]["new"][2] += f["delays_s"]
        om, oidx, _typ = (deployed.models.get(s.spec.node_type) or deployed.models.get("default"))
        ocols = [COLS[i] for i in oidx]
        ook = ~np.isnan(X[:, oidx]).any(axis=1)
        oseg = ev.Segment(s.spec.name, s.spec.interval_s, t[ook], X[ook][:, oidx])

        def score_old(Z, _t=None, _i=None, node=s.spec.node_type, idx=oidx):
            full = np.full((len(Z), len(COLS)), np.nan)
            full[:, idx] = Z
            return deployed.score(node, full)

        found_old = ev.detection([oseg], ocols, score_old, replay_fn=old_replay)
        for f in found_old["faults"]:
            faults[f["kind"]]["old"][0] += f["trials"]
            faults[f["kind"]]["old"][1] += f["caught"]
            faults[f["kind"]]["old"][2] += f["delays_s"]
    return {"seed": seed, "rows": rows, "faults": faults, "outcome": outcome, "bundle": outcome.bundle, "sims": sims, "datas": datas,
            "train_s": train_s}


def _fmt_delay(delays):
    return "-" if not delays else f"{np.median(delays):.0f} s"


def _delay(delays):
    return "-" if not delays else f"{np.median(delays):.0f} s"


def report(results) -> str:
    """The two tables for one run or for several seeds, each seed on its own and then the mean of the seeds."""
    results = [results] if isinstance(results, dict) else list(results)
    out = io.StringIO()
    w = out.write
    w("PHAEMOS anomaly model evaluation on SIMULATED data. No real machine data has been used.\n")
    seeds = ", ".join(str(r["seed"]) for r in results)
    w(f"Fixed seeds {seeds}: {len(results[0]['rows'])} machines each, {TRAIN_DAYS} days to learn from and {TEST_DAYS} healthy days to test on.\n\n")
    w("Table 1. False anomaly alerts per machine per week on healthy data (budget: 1.0 or fewer)\n")
    names = [r["name"] for r in results[0]["rows"]]
    w(f"{'machine':<10}{'node':<8}{'every':>6}")
    for r in results:
        w(f"  | seed {r['seed']}: {'OLD dep':>8}{'OLD good':>9}{'NEW':>6}")
    w(f" | mean: {'OLD dep':>8}{'OLD good':>9}{'NEW':>6}\n")
    means = {"dep": [], "good": [], "new": []}
    for i, name in enumerate(names):
        first = results[0]["rows"][i]
        w(f"{name:<10}{first['node']:<8}{str(first['interval']) + ' s':>6}")
        dep, good, new = [], [], []
        for r in results:
            row = r["rows"][i]
            dep.append(row["old_deployed"])
            good.append(row["old_good"])
            n = row["new"]
            new.append(n)
            w(f"  |{'':<7}{'':<1}{row['old_deployed']:>8.1f}{row['old_good']:>9.1f}{'n/a' if n is None else format(n, '.1f'):>6}")
        got = [v for v in new if v is not None]
        w(f" |{'':<6}{np.mean(dep):>8.1f}{np.mean(good):>9.1f}{(format(np.mean(got), '.1f') if got else 'n/a'):>6}\n")
        means["dep"].append(np.mean(dep))
        means["good"].append(np.mean(good))
        means["new"].extend(got)
    w(f"{'worst NEW on any machine and seed':<24}{max(means['new']):>6.1f}   mean NEW {np.mean(means['new']):.2f}   mean OLD deployed {np.mean(means['dep']):.1f}   mean OLD good {np.mean(means['good']):.1f}\n")
    w("OLD dep: contamination 0.05 and the newest 10,000 rows of the table and three anomalous readings in a row.\n")
    w("OLD good: the same model and rule fitted on 10,000 rows spread over the fortnight.\n")
    w("NEW: forest and per-sensor baseline on measured boundaries and clean rows and the sustained-window decision.\n")
    w("n/a: no model was accepted for that machine, so it raises no anomaly alert.\n\n")
    w("Table 2. Injected faults, caught or missed and how soon (summed over the machines that carry the sensor)\n")
    w(f"{'fault':<18}")
    for r in results:
        w(f"| seed {r['seed']}: {'OLD':>9}{'NEW':>9} ")
    w(f"| all seeds: {'OLD':>9}{'NEW':>9}  median delay OLD / NEW\n")
    for kind in results[0]["faults"]:
        w(f"{kind:<18}")
        tot = {"old": [0, 0, []], "new": [0, 0, []]}
        if ev.FAULTS[kind].get("handled"):
            w("handled by the sensor health check (a sensor whose value stops moving is a sensor fault)\n")
            continue
        for r in results:
            f = r["faults"][kind]
            for side in ("old", "new"):
                tot[side][0] += f[side][0]
                tot[side][1] += f[side][1]
                tot[side][2] += f[side][2]
            w(f"| {'':<11}{str(f['old'][1]) + '/' + str(f['old'][0]):>9}{str(f['new'][1]) + '/' + str(f['new'][0]):>9} ")
        w(f"| {'':<10}{str(tot['old'][1]) + '/' + str(tot['old'][0]):>9}{str(tot['new'][1]) + '/' + str(tot['new'][0]):>9}  {_delay(tot['old'][2])} / {_delay(tot['new'][2])}\n")
    w("Faults (sizes are the simulator's): its overheat jumping to full for an hour and ramped to full over six hours and its\n")
    w("bearing fault ramped to full over two hours and the current at four times for ten minutes. Delay is the median time\n")
    w("from the fault starting to the alert. The faults are injected into the healthy test week of every machine.\n\n")
    w("Models trained by the new retrain (first seed):\n")
    for r in results[0]["outcome"].models:
        fa = r.get("false_alerts_per_week")
        line = "" if fa is None else f"held-out false alerts {fa:.2f} per week, boundary tightened {r.get('tightenings', 0)} times"
        w(f"  {r['label']:<24}{r['state']:<9}{line}\n")
        if r["state"] != "ready" and r.get("message"):
            w(f"      {r['message']}\n")
    w("\nWhat simulated data cannot show: how a real plant drifts and what its real faults look like and how its operators\n")
    w("load it. The budget here is a measurement on readings the model did not train on. It is not a guarantee.\n")
    return out.getvalue()


def timings(result: dict) -> str:
    """Bundle size and load time, scoring time per reading with the detector and memory per model, on this machine."""
    import tracemalloc
    bundle = result["bundle"]
    buf = io.BytesIO()
    joblib.dump(bundle, buf)
    models = ml._models_in(bundle)
    full = [m for m in models if hasattr(m, "estimators_")]
    lines = [f"bundle size: {len(buf.getvalue()) / 1e6:.2f} MB for {len(models)} models ({len(full)} with a forest)"]
    start = time.perf_counter()
    joblib.load(io.BytesIO(buf.getvalue()))
    lines.append(f"bundle load: {(time.perf_counter() - start) * 1000:.0f} ms")
    tracemalloc.start()
    loaded = joblib.load(io.BytesIO(buf.getvalue()))
    packs = [ml._pack(m) for m in ml._models_in(loaded) if hasattr(m, "estimators_")]
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if packs:
        lines.append(f"memory of the loaded bundle with its trees packed: {current / 1e6:.1f} MB, about "
                     f"{current / 1e6 / len(packs):.1f} MB per full model")
    for m in models:
        if getattr(m, "phaemos_detector", None) is not None:
            parts = io.BytesIO()
            joblib.dump((m.phaemos_detector, m.phaemos_baseline), parts)
            lines.append(f"the baseline and detector of one machine (all a light model holds) pickle to "
                         f"{len(parts.getvalue()) / 1e3:.0f} kB")
            break
    s = result["sims"][0]
    previous, store = ml._model, ml._state_store
    ml._model = bundle
    ml._state_store = ml.cd.MemoryStateStore()
    try:
        _, test = _split(s)
        idx = [i for i in range(len(COLS)) if not np.isnan(s.X[100, i])]
        rows = [{**{COLS[i]: float(s.X[j, i]) for i in idx}, "node_type": s.spec.node_type} for j in range(2000)]
        moments = [datetime.fromtimestamp(START + 5.0 * j, tz=timezone.utc) for j in range(2000)]
        for j in range(200):
            ml.score_reading(rows[j], device_id=s.spec.name, at=moments[j])
        start = time.perf_counter()
        for j in range(200, 2000):
            ml.score_reading(rows[j], device_id=s.spec.name, at=moments[j])
        lines.append(f"score one reading with its machine's model (forest, baseline and detector): "
                     f"{(time.perf_counter() - start) / 1800 * 1000:.3f} ms")
    finally:
        ml._model, ml._state_store = previous, store
    lines.append(f"training: {result.get('train_s', float('nan')):.0f} s for {len(result['sims'])} machines and their pools")
    return "\n".join(line for line in lines if line)


# -- the full evaluation ------------------------------------------------------------------------------------------
#
# everything below measures the model the way the review measured it and more: false alerts per machine-week on healthy
# test weeks under the regime changes a real plant has (with exact Poisson intervals), detection of faults of several
# sizes and shapes with a stated deadline, the time to detect and the machines no model watches, which count in every
# figure. Nothing here is real data.

# the review's regime changes after training. The second element says how the test week is changed: a knob of simulate
# (the whole fleet is simulated again with it) or a change to the test rows (resample, drop, gaps)
REGIMES = {
    "none": ({}, {}),
    "hotter week +3 C": ({"ambient_test": 3.0}, {}),
    "seasonal drift 0.3 C a day": ({"season_ramp": 0.3}, {}),
    "lighter product (load x0.7)": ({"load_scale": 0.7}, {}),
    "24 h duty": ({"always_on": 1}, {}),
    "temperature noise x3 (test)": ({"temp_noise_test": 3.0}, {}),
    "posting interval x2": ({}, {"resample": 2}),
    "posting interval x6": ({}, {"resample": 6}),
    "20% of readings lost": ({}, {"drop": 0.2}),
    "30 s outage every 10 min": ({}, {"gaps": (600, 30)}),
}
# the regimes whose detection is measured too (fewer faults and trials than the healthy week, to bound the run time)
DETECTION_REGIMES = ("hotter week +3 C", "seasonal drift 0.3 C a day", "lighter product (load x0.7)", "posting interval x6",
                     "20% of readings lost", "30 s outage every 10 min")
# the regimes that change the training fortnight too, so the fleet is trained again on them
TRAINED_REGIMES = {
    "humidity no longer tied to the room": {"free_humidity": 1},
    "temperature noise x3 all along": {"temp_noise_all": 3.0},
}


def machine_temperature(cols) -> list[str]:
    """The columns a machine's own heat moves: its surface sensors when it has them, else its only temperature."""
    surface = [c for c in ("contact_temp", "ir_temperature") if c in cols]
    return surface or (["temperature"] if "temperature" in cols else [])


def fault_catalogue(cols, full: bool = True) -> dict:
    """
    The faults of the full evaluation for a machine with these columns, by name. Additive faults are stated in the
    sensor's own unit. Each has the deadline within which an alert counts as catching it.
    """
    out: dict = {}
    temps = machine_temperature(cols)

    def heat(amount):
        # an infrared sensor sees a little more of a hot surface than a contact probe does
        return {c: amount * (1.2 if c == "ir_temperature" else 1.0) for c in temps}

    if temps:
        for size in ((1, 2, 3, 5, 8) if full else (2, 3, 5)):
            out[f"temperature step +{size} C, 1 h"] = {"add": heat(size), "seconds": 3_600, "deadline_s": 1_800}
        if full:
            out["temperature step +3 C at a start-up"] = {"add": heat(3), "seconds": 3_600, "deadline_s": 1_800,
                                                          "at_startup": True}
            out["slow drift +0.5 C an hour for 6 h"] = {"add": heat(3), "ramp": True, "seconds": 21_600,
                                                        "deadline_s": 21_600}
        out["slow drift +2 C an hour for 6 h"] = {"add": heat(12), "ramp": True, "seconds": 21_600, "deadline_s": 21_600}
        if full:
            out["intermittent +5 C, 10 min on and 10 min off, 4 h"] = {
                "add": heat(5), "intermittent": (600, 600), "seconds": 14_400, "deadline_s": 3_600}
            out["+4 C only while running, 8 h"] = {"add": heat(4), "running_only": True, "seconds": 28_800,
                                                   "deadline_s": 7_200}
    vib = [c for c in ("vibration_x", "vibration_y", "vib_magnitude") if c in cols]
    if vib:
        if full:
            out["vibration +50% ramped over 2 h"] = {"columns": {c: 1.5 for c in vib}, "ramp": True, "seconds": 7_200,
                                                     "deadline_s": 7_200}
        out["vibration x2 step, 1 h"] = {"columns": {c: 2.0 for c in vib}, "seconds": 3_600, "deadline_s": 1_800}
    cur = [c for c in ("current_ma", "power_mw") if c in cols]
    if cur:
        if full:
            out["current +10% step, 1 h"] = {"columns": {c: 1.1 for c in cur}, "seconds": 3_600, "deadline_s": 1_800}
        out["current +25% step, 1 h"] = {"columns": {c: 1.25 for c in cur}, "seconds": 3_600, "deadline_s": 1_800}
    # the simulator's own faults, which a model must clear to be used (multiples of the healthy value)
    for kind, spec in ev.FAULTS.items():
        if not spec.get("handled") and (full or kind in ("temperature_step", "vibration_rise")):
            out[f"simulator {kind.replace('_', ' ')} (x{max((spec['columns'] or {}).values(), default=0):g})"] = spec
    return out


def test_rows(sim: Sim, change: dict, idx: list[int], rng_seed: int = 99):
    """The machine's test week with a change to its rows (resample, drop, gaps), cut to readings with every column."""
    cut = START + TRAIN_DAYS * DAY
    t, X = sim.times, sim.X
    test = t >= cut
    t, X = t[test], X[test]
    rng = np.random.default_rng(rng_seed + sim.index)
    if change.get("resample"):
        sel = np.arange(0, len(t), change["resample"])
        t, X = t[sel], X[sel]
    if change.get("drop"):
        keep = rng.random(len(t)) > change["drop"]
        t, X = t[keep], X[keep]
    if change.get("gaps"):
        every, length = change["gaps"]
        keep = ((t - t[0]) % every) >= length
        t, X = t[keep], X[keep]
    ok = ~np.isnan(X[:, idx]).any(axis=1)
    return t[ok], X[ok][:, idx]


def pick_model(bundle: dict, sim: Sim):
    """The model that would score this machine in service and its key or (None, None) when none would."""
    previous = ml._model
    ml._model = bundle
    try:
        for key, model in ml._candidates({"node_type": sim.spec.node_type}, sim.spec.name):
            if all(c in sim.spec.cols or c == td.AMBIENT_REF for c in model.phaemos_features):
                return key, model
    finally:
        ml._model = previous
    return None, None


def _live_scores(model, t, X, interval_s):
    """Scores of a test week as the live path gives them: from the state the model starts in service with."""
    return ml.score_sequence(model, t, X, interval_s, state=ml._fresh_state(model))


def evaluate_machine(model, sim: Sim, change: dict, catalogue: dict | None, trials: int) -> dict:
    cols = list(model.phaemos_features)
    idx = [COLS.index(c) for c in cols]
    t, X = test_rows(sim, change, idx)
    interval = sim.spec.interval_s * change.get("resample", 1)
    out = {"weeks": float((t[-1] - t[0]) / (7 * DAY)) if len(t) > 1 else 0.0}
    scores = _live_scores(model, t, X, interval)
    rp = ev.replay(t, scores, interval)
    out["false"] = len(rp.raises)
    out["false_at_h"] = [round((r["time"] - START - TRAIN_DAYS * DAY) / 3600.0, 1) for r in rp.raises][:10]
    out["over_share"] = round(float((scores >= ml.ANOMALY_THRESHOLD).mean()), 4)
    if catalogue:
        seg = ev.Segment(sim.spec.name, interval, t, X)

        def fn(Z, tt, i):
            return ml.score_sequence(model, tt, Z, i, prime=True)

        found = ev.detection([seg], cols, fn, faults=catalogue, trials=trials)
        out["faults"] = {f["kind"]: {"caught": f["caught"], "trials": f["trials"], "delays_s": f["delays_s"]}
                         for f in found["faults"] if not f.get("handled")}
    return out


def evaluate_full(seed: int, regimes=None, trained_regimes=None, fleet=None, trials: int = 4,
                  regime_trials: int = 2, base_knobs: dict | None = None) -> dict:
    """One seed of the full evaluation: train on the fortnight, then every regime's test week and every fault."""
    fleet = fleet or FULL_FLEET
    regimes = REGIMES if regimes is None else regimes
    trained_regimes = TRAINED_REGIMES if trained_regimes is None else trained_regimes
    base_knobs = base_knobs or {}
    out = {"seed": seed, "machines": [s.name for s in fleet], "regimes": {}, "records": [], "base_knobs": base_knobs}
    base_sims = simulate_fleet(fleet=fleet, seed=seed, knobs=base_knobs or None)
    started = time.time()
    outcome, _ = train_new(base_sims)
    out["train_s"] = round(time.time() - started, 1)
    out["records"] = [{k: r.get(k) for k in ("label", "state", "message", "light", "false_alerts_per_week",
                                             "false_alerts_per_week_high_95", "detector", "tightenings")}
                      for r in outcome.models]
    out["unmonitored"] = outcome.unmonitored
    bundles = {"": outcome.bundle}
    for label, knobs in trained_regimes.items():
        sims = simulate_fleet(fleet=fleet, seed=seed, knobs={**base_knobs, **knobs})
        bundles[label] = train_new(sims)[0].bundle
    for label, (knobs, change) in list(regimes.items()) + [(k, (v, {})) for k, v in trained_regimes.items()]:
        sims = base_sims if not knobs else simulate_fleet(fleet=fleet, seed=seed, knobs={**base_knobs, **knobs})
        bundle = bundles.get(label if label in trained_regimes else "")
        rows = {}
        for sim in sims:
            key, model = pick_model(bundle, sim) if bundle else (None, None)
            if model is None:
                rows[sim.spec.name] = {"key": None, "unmonitored": True}
                continue
            catalogue = fault_catalogue(model.phaemos_features, full=(label == "none")) \
                if label == "none" or label in DETECTION_REGIMES else None
            res = evaluate_machine(model, sim, change, catalogue, trials if label == "none" else regime_trials)
            res["key"] = key
            res["scope"] = "machine" if key.startswith("machine:") else key
            res["light"] = not ml._has_forest(model)
            rows[sim.spec.name] = res
        out["regimes"][label] = rows
    return out


BOOTSTRAP_DRAWS = 2000


def cluster_interval(units: list, kind: str = "rate") -> tuple[float, float]:
    """
    A 95 per cent interval that respects the grouping: a bootstrap over (seed, machine) units, each resampled whole.

    units are (events, exposure) pairs: (alerts, machine-weeks) for a rate and (caught, trials) for a share. Machine-weeks
    are not independent (a machine that raises once tends to raise again: the healthy counts are overdispersed) and the
    trials of one machine are not either, so the unit of resampling is the machine-seed and not the week or the trial.
    """
    units = [(float(a), float(b)) for a, b in units if b > 0]
    if not units:
        return float("nan"), float("nan")
    rng = np.random.default_rng(20261122)
    arr = np.array(units)
    picks = rng.integers(0, len(arr), size=(BOOTSTRAP_DRAWS, len(arr)))
    sums = arr[picks].sum(axis=1)
    stats = sums[:, 0] / np.maximum(sums[:, 1], 1e-12)
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def tune(seeds, settings: list, out: str | None = None) -> list:
    """
    The tuning of the change detector: light models on the machines with a temperature, one run per setting, false alerts
    on the seed's test week (as is, 3 °C warmer, a seasonal drift) and detection of additive steps and a slow drift.

    It refuses any seed the manifest lists as a test seed, so the reported figures can never have been tuned on.
    """
    import json
    test = set(seed_manifest()["test"])
    if any(seed in test for seed in seeds):
        raise ValueError("the tuning was asked to read a test seed; it reads only the manifest's validation seeds")
    from app.services import change_detector as cd
    results = []
    for seed in seeds:
        machines = [m for m in FULL_FLEET if machine_temperature(m.cols)]
        regimes = {"none": {}, "hotter": {"ambient_test": 3.0}, "season": {"season_ramp": 0.3}}
        sims = {lab: simulate_fleet(fleet=machines, seed=seed, knobs=k) for lab, k in regimes.items()}
        cut = START + TRAIN_DAYS * DAY
        datas = []
        for sim in sims["none"]:
            tr = sim.times < cut
            datas.append(td.select_from_arrays(sim.times[tr], sim.X[tr], sim.reasons[tr], sim.spec.interval_s,
                                               device_id=sim.spec.name, name=sim.spec.name, node_type=sim.spec.node_type))
        saved = (cd.ALLOWANCE, cd.LEVEL_TAU_S, cd.LEVEL_BOUND, ev.TRIALS)
        try:
            ev.TRIALS = 1
            for setting in settings:
                cd.ALLOWANCE, cd.LEVEL_TAU_S, cd.LEVEL_BOUND = setting["k"], setting["tau_h"] * 3600.0, setting["bound"]
                row = {"seed": seed, "setting": setting, "machines": {}}
                for i, m in enumerate(datas):
                    cols = ml._select([m.fit, m.held])
                    scope = ml._scope_from(f"machine:{m.device_id}", "machine", m.name, cols, [m.fit],
                                           [(m, m.val, m.val_times)], m.clean_hours, m.span_hours, m.refused, m.fit_times,
                                           m.interval_s, tests=[(m, m.test, m.test_times)], light=True)
                    model, rec = ml.fit_model(scope)
                    entry = {"state": rec["state"]}
                    if model is not None:
                        idx = [COLS.index(c) for c in model.phaemos_features]
                        for lab in regimes:
                            t, X = test_rows(sims[lab][i], {}, idx)
                            entry[f"fa_{lab}"] = len(ev.replay(t, _live_scores(model, t, X, m.interval_s), m.interval_s).raises)
                        t, X = test_rows(sims["none"][i], {}, idx)
                        cat = {f"step+{d}": {"add": {c: d for c in machine_temperature(cols)}, "seconds": 3600,
                                             "deadline_s": 1800} for d in (1, 2, 3, 5)}
                        cat["drift0.5/h"] = {"add": {c: 3.0 for c in machine_temperature(cols)}, "ramp": True,
                                             "seconds": 21600, "deadline_s": 21600}
                        found = ev.detection([ev.Segment(m.name, m.interval_s, t, X)], list(model.phaemos_features),
                                             lambda Z, tt, iv, mod=model: ml.score_sequence(mod, tt, Z, iv, prime=True),
                                             faults=cat, trials=3)
                        entry["det"] = {f["kind"]: [f["caught"], f["trials"]] for f in found["faults"]}
                    row["machines"][m.name] = entry
                results.append(row)
                if out:
                    with open(out, "a") as handle:
                        handle.write(json.dumps(row) + "\n")
        finally:
            cd.ALLOWANCE, cd.LEVEL_TAU_S, cd.LEVEL_BOUND, ev.TRIALS = saved
    return results


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z = 1.96
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def full_report(results: list[dict]) -> str:
    """The whole table for several seeds: false alerts per machine-week with a 95 per cent interval and detection."""
    buf = io.StringIO()
    w = buf.write
    seeds = ", ".join(str(r["seed"]) for r in results)
    fleet = results[0]["machines"]
    w("PHAEMOS anomaly model, full evaluation on SIMULATED data. No real machine data has been used.\n")
    w(f"Seeds {seeds} (none of them was used to choose a setting). {len(fleet)} machines a seed: {', '.join(fleet)}.\n")
    w(f"Each machine learns from {TRAIN_DAYS} days and is tested on the {TEST_DAYS} days after them.\n\n")
    w("Table A. False alerts per machine-week on healthy test weeks, with a 95 per cent interval from a bootstrap over\n")
    w("machine-seeds (each machine's week resampled whole, because a machine that raises once tends to raise again).\n")
    w("Unmonitored: machine-seeds with no model at all, which raise nothing and are counted here, not hidden.\n")
    w("The last two columns split the rate by machines with an ambient reference (an air temperature beside a machine\n")
    w("temperature) and machines without one.\n")
    w(f"{'regime':<40}{'alerts':>7}{'mach-wk':>9}{'per wk':>8}{'95% interval':>17}{'unmonitored':>13}{'ambient':>9}{'no ref':>8}\n")
    labels = []
    for r in results:
        labels += [k for k in r["regimes"] if k not in labels]
    for label in labels:
        alerts = weeks = 0.0
        unmon = total = 0
        split = {True: [0, 0.0], False: [0, 0.0]}
        units = []
        for r in results:
            for name, row in r["regimes"].get(label, {}).items():
                total += 1
                if row.get("unmonitored"):
                    unmon += 1
                    continue
                alerts += row["false"]
                weeks += row["weeks"]
                units.append((row["false"], row["weeks"]))
                ambient = name.startswith("mill-")
                split[ambient][0] += row["false"]
                split[ambient][1] += row["weeks"]
        if not total:
            continue
        lo, hi = cluster_interval(units)
        w(f"{label:<40}{int(alerts):>7}{weeks:>9.1f}{(alerts / weeks if weeks else float('nan')):>8.2f}"
          f"{'' if lo is None else f'{lo:.2f} to {hi:.2f}':>17}{f'{unmon} of {total}':>13}"
          f"{(split[True][0] / split[True][1] if split[True][1] else float('nan')):>9.2f}"
          f"{(split[False][0] / split[False][1] if split[False][1] else float('nan')):>8.2f}\n")
    w("\nTable B. Detection on the healthy test week, by fault, over every machine that carries the sensor.\n")
    w("Caught means an alert within the deadline after the onset. Unmonitored machines count as missed. The interval is a\n")
    w("bootstrap over machine-seeds (a machine's trials resampled together). A detection trial starts primed: its slow levels\n")
    w("are set from its own first healthy hour, as a machine in service has them. A healthy week starts cold.\n")
    w(f"{'fault':<52}{'deadline':>9}{'caught':>9}{'share':>7}{'95% interval':>15}{'median':>8}{'p90':>8}\n")
    kinds: dict = {}
    for r in results:
        for name, row in r["regimes"]["none"].items():
            for kind, f in (row.get("faults") or {}).items():
                acc = kinds.setdefault(kind, {"caught": 0, "trials": 0, "delays": [], "units": []})
                acc["caught"] += f["caught"]
                acc["trials"] += f["trials"]
                acc["delays"] += f["delays_s"]
                acc["units"].append((f["caught"], f["trials"]))
    deadlines = {**fault_catalogue(STM), **fault_catalogue(ESP)}
    for kind, acc in kinds.items():
        lo, hi = cluster_interval(acc["units"])
        d = np.array(acc["delays"]) / 60.0
        limit = (deadlines.get(kind) or {}).get("deadline_s")
        w(f"{kind:<52}{(f'{limit / 60:.0f} m' if limit else '-'):>9}{acc['caught']:>5}/{acc['trials']:<3}"
          f"{(acc['caught'] / acc['trials'] if acc['trials'] else 0):>7.0%}"
          f"{f'{lo:.0%} to {hi:.0%}':>15}{(f'{np.median(d):.0f} m' if len(d) else '-'):>8}"
          f"{(f'{np.percentile(d, 90):.0f} m' if len(d) else '-'):>8}\n")
    w("\nTable C. Detection under each regime (fewer faults and trials), caught of trials over monitored machines.\n")
    for label in labels:
        if label == "none":
            continue
        acc = {}
        for r in results:
            for name, row in r["regimes"].get(label, {}).items():
                for kind, f in (row.get("faults") or {}).items():
                    a = acc.setdefault(kind, [0, 0])
                    a[0] += f["caught"]
                    a[1] += f["trials"]
        cells = "; ".join(f"{k}: {v[0]}/{v[1]}" for k, v in acc.items())
        w(f"  {label}: {cells}\n")
    w("\nWhat simulated data cannot show: real fault sizes and shapes, real seasonal and duty drift against the nightly\n")
    w("retrain and real delivery latency and jitter. Only real machines can settle those.\n")
    return buf.getvalue()


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def main(argv=None) -> None:
    import json
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--seeds", type=int, default=3, help="how many seeded weeks of the short comparison to run (default 3)")
    parser.add_argument("--timings", action="store_true", help="also print bundle size and scoring time (these vary by machine)")
    parser.add_argument("--full", type=str, default=None,
                        help="run the full evaluation on these comma separated seeds ('test' for TEST_SEEDS) and append "
                             "one JSON line per seed to --out")
    parser.add_argument("--out", type=str, default=None, help="where the full evaluation appends its JSON lines")
    parser.add_argument("--report", type=str, default=None, help="print the full report from these comma separated JSON line files")
    parser.add_argument("--no-retrained", action="store_true", help="skip the regimes that need the fleet trained again")
    parser.add_argument("--knobs", type=str, default=None, help="simulator knobs for every week, as JSON (site_reference)")
    parser.add_argument("--regimes", type=str, default=None, help="only these regimes, comma separated")
    parser.add_argument("--tune", type=str, default=None,
                        help="tune the change detector over these settings (a JSON list of {k, tau_h, bound}) on the "
                             "manifest's validation seeds and append one JSON line per setting to --out")
    args = parser.parse_args(argv)
    if args.tune:
        tune(VALIDATION_SEEDS, json.loads(args.tune), args.out)
        return
    if args.report:
        results = []
        for path in args.report.split(","):
            with open(path) as handle:
                results += [json.loads(line) for line in handle if line.strip()]
        sys.stdout.write(full_report(results))
        return
    if args.full:
        seeds = TEST_SEEDS if args.full == "test" else tuple(int(x) for x in args.full.split(","))
        for seed in seeds:
            started = time.time()
            regimes = None if not args.regimes else {k: v for k, v in REGIMES.items() if k in args.regimes.split(",")}
            result = evaluate_full(seed, regimes=regimes, trained_regimes={} if args.no_retrained else None,
                                   base_knobs=json.loads(args.knobs) if args.knobs else None)
            result["seconds"] = round(time.time() - started, 1)
            line = json.dumps(_jsonable(result))
            if args.out:
                with open(args.out, "a") as handle:
                    handle.write(line + "\n")
            sys.stdout.write(f"seed {seed} done in {result['seconds']:.0f} s\n")
            sys.stdout.flush()
        return
    results = [evaluate(seed=SEED + 1000 * k) for k in range(args.seeds)]
    sys.stdout.write(report(results))
    if args.timings:
        sys.stdout.write("\nMeasured on this machine (not part of the tables):\n" + timings(results[0]) + "\n")


if __name__ == "__main__":
    main()
