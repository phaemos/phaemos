# API Reference

Base URL: `https://api.phaemos.com/api/v1` (production) or `http://localhost:8000/api/v1` (local)

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

## Authentication

**Device ingestion** uses an API key header:

```text
X-API-Key: <device api key>
```

**User routes** use a Bearer JWT token (15-minute expiry):

```text
Authorization: Bearer <access_token>
```

**Scripts and the command line tool** use an API token (`Authorization: Bearer pht_...`), which needs no password. See [API tokens](#api-tokens). An integration that must outlive a person uses a [service account](#service-accounts).

**Token refresh** uses a 7-day httpOnly cookie (no header needed - the browser sends it automatically).

**Every access token names a live session** (the `sid` claim). A token with none is refused (`401`) outside development, so a token minted by someone who holds the signing key cannot skip revocation. Access tokens issued before sessions existed lived 15 minutes and were gone long ago, so no one is signed out by this rule. Each kind of token (access, refresh, sign-in challenge, provider link, password reset, known-browser cookie) is signed with its own key derived from `SECRET_KEY`, so a token for one purpose is refused for another. After a key rotation `SECRET_KEY_PREVIOUS` still verifies what the old key signed and signs nothing.

**Dangerous admin actions need a fresh proof.** These routes read `password` and, when two-step is on, `code` from the JSON body (two extra form fields on the multipart firmware upload), with the same messages and status codes as the profile proof routes (`400` for a missing or wrong proof, never `401`; a provider-only account proves it with a provider sign-in in the last 5 minutes on this session; 20 proofs a minute for each account):

| Route | Asks when | Message action |
| --- | --- | --- |
| `POST /auth/invite` | the role is `admin` | `invite an admin` |
| `POST /webhooks` | always | `add a webhook` |
| `PATCH /webhooks/{id}` | always | `change a webhook` |
| `POST /firmware/upload` | always | `upload firmware` |
| `POST /devices/{id}/rotate-key` | always (an owner, who is not an admin, proves it with their own password) | `rotate this machine's key` |
| `POST /auth/users/{id}/deactivate`, `/reactivate`, `PATCH /auth/users/{id}/role`, `POST /auth/users/{id}/clear-two-step`, `POST /auth/users/{id}/reset-link`, `DELETE /auth/users/{id}`, `DELETE /auth/invitations/{id}` | always | `deactivate this account`, `reactivate this account`, `change this account's role`, `clear this account's two-step sign-in`, `send a password reset link`, `remove this account`, `cancel this invitation` |

**Environment.** `ENVIRONMENT` is `production` unless a developer sets `development`. An unset, empty or unknown value is production. Development relaxes a fixed list of controls (open registration, the API docs, insecure cookies, http webhooks, no Turnstile, a weak signing key, the `?token=` socket address, INFO logs, skipped emails, the demo feed) and only runs against a database on the same machine. `TRUSTED_PROXIES` is empty by default, so forwarded headers are ignored until the one proxy address is set. The start-up log says which mode and which proxy setting is in force.

Every token states its purpose (access, refresh or sign-in challenge) and is only accepted for that purpose. Changing the password or turning two-factor authentication on or off ends every other session for the account. Wrong passwords and wrong authentication codes alike are slowed down, never locked: five failures from one place make that place wait (30 seconds, then longer) and an account being guessed at from many places slows only the browsers that have not signed in to it before. See "Sign-in slowdown" under `POST /auth/login`.

---

## Telemetry

### POST /telemetry

Ingest a sensor reading. Called by ESP32/firmware every cycle.

**Auth:** `X-API-Key`

**Request body:**

```json
{
  "device_id": "uuid",
  "temperature": 34.2,
  "humidity": 61.5,
  "pressure": 1013.2,
  "vibration_x": 0.12,
  "vibration_y": -0.04,
  "vibration_z": 9.81,
  "gyro_x": 0.01,
  "gyro_y": -0.02,
  "gyro_z": 0.00,
  "bus_voltage": 5.1,
  "current_ma": 320.0,
  "power_mw": 1632.0,
  "ir_temperature": 42.5,
  "distance_mm": 185,
  "gas_level": 120,
  "gas_alert": false,
  "shaft_angle": 45.0,
  "shaft_rpm": 1200.0,
  "sound_level": 520,
  "contact_temp": 38.1,
  "light_level": 512,
  "moisture_level": 230,
  "water_detected": false,
  "fft_peak_hz": 62.5,
  "vib_magnitude": 0.87,
  "node_type": "esp32"
}
```

**`recorded_at` and `observed_at`.** `recorded_at` is the time the server **received** the reading. A gateway that spools readings through an outage (the edge gateway keeps them for up to 7 days) may add `observed_at`, the ISO 8601 time the reading was taken, so a backlog is ordered and charted where it belongs. The rules:

- It is honoured only in the past and by at most 7 days. Older than that is refused (`422 observed_at_too_old`, the reading is not stored and its pair is not used up). A time in the future is never believed: up to 60 seconds ahead is a fast clock and is read as "now", anything later is ignored, the reading is stored at the time it was received and `quality.observed_at_ignored` says `future`.
- It decides ordering only: `recorded_at` takes its value, so charts, exports, `/latest` and the history windows place the reading at the time it was taken. The device's own clock (`ts`) is stored as `device_ts` for display and for spotting a node whose clock is wrong. It never decides ordering and never decides whether a reading is current.
- A reading older than a live one (older than the larger of 30 seconds and 3 posting intervals) is a **backlog reading**. It is stored and charted at its own time and nothing more: it is not scored (`anomaly_score` is null), no alert rule and no anomaly window judges it, no alert or notification comes from it, no live broadcast goes out, it does not touch the health row or the sensor fault alerts and it does not mark the machine online or end a silent-node alert (its `last_seen` only moves forward to the reading's own time). `quality.backlog` is true and `quality.received_at` says when it arrived. A drained backlog therefore never looks like the machine's present state.
- A reading with no `observed_at` is stamped with the arrival time as before.

**`device_id` in the body is optional and ignored.** The machine is the one the `X-API-Key` belongs to, so a body cannot name another. A client may send its own label or leave the field out.

**Replay protection.** A node that sends `boot` and `seq` together is protected from then on. Each post is judged under the machine's lock against the pair of the last post accepted (`boot` first, then `seq`). These answers are exact and stable, so a client can code against them:

| Post | Status | Body |
|---|---|---|
| a newer pair | `201` | the stored reading, as always. The pair is kept |
| the exact pair last accepted | `200` | `{"status": "duplicate", "stored": false, "detail": "this boot and seq were already accepted"}` |
| an older pair | `409` | `{"detail": "this post's boot and seq are older than the last one accepted for this machine. If its flash was wiped an admin can accept a new counter"}` |
| no pair (or only half of it) from a machine that has sent the pair | `409` | `{"detail": "this machine always sends boot and seq and this post did not carry both"}` |
| a `boot` over 2,100,000,000 or a `seq` over 4,000,000,000 | `422` | `{"detail": "this boot or seq is higher than any machine could reach, so it was refused. If it came from the machine itself its counter is damaged"}` |
| no pair from a machine that has never sent one | `201` | accepted as before. The machine shows `replay_protected: false` |

How a client should treat them: `201` is stored. `200` with `"status": "duplicate"` means this exact post was already stored (its answer was lost), so the client should treat it as a success and move on without sending it again. `409` is a refusal that will not change by retrying the same post: the client must not loop on it and should report it (a streak of them is the sign of a wiped flash or a replayed capture). `422` is a bad value and is never retried. A duplicate is **not** a heartbeat: it stores nothing, does not move `last_seen` or `link_state`, runs no rule or alert and is not counted as a refusal. A `409` or `422` stores nothing, is no heartbeat and runs no rule or alert. It counts in `replay_refused` (a duplicate does not). The pair is checked once the key (`401`), the rate limit (`429`) and the shape of the body (`422`) have passed. It is checked before anything in the reading is used.

A `boot` that rises by more than 1,000 in one post is accepted (`201`). So is a `seq` that rises by more than 1,000,000 within one boot. Each is recorded: the machine shows `counter_jump_at`, `counter_jump_note` and `replay_warning`, which says the key may be known to someone else and should be rotated. The first pair a machine sends is never a warning. Nor is a restart that adds one. A Pico that moves from a small counter to Unix seconds shows the warning once. `GET /devices` and `GET /devices/{id}` return `replay_protected`, `last_boot`, `last_seq`, `replay_refused` (refusals since the last accepted post), `replay_refused_at`, `counter_jump_at`, `counter_jump_note`, `replay_warning`, `replay_recovery` (the text for the accept-counter action, which says to rotate the key as well when the counter was pushed up and not wiped) and `replay_status`, a plain sentence for the health panel. From three refusals in a row `replay_status` says an admin can accept a new counter (`POST /devices/{id}/accept-counter`, which clears the warning and the streak and is audited with `key_rotation_advised=true` when a jump was on record). This does not stop someone who holds the key from posting pairs that are newer than the last: that is what hashed keys, TLS and key rotation are for.

**Range of a value.** Every sensor field has a physical range wider than its part's data sheet (for example `temperature` -90 to 250, `humidity` 0 to 100, `pressure` 300 to 1100, `vibration_x` -160 to 160, `bus_voltage` 0 to 32, `contact_temp` -55 to 125). A value outside it is dropped (stored as null), named in `quality.dropped_values` and the sensor that makes it is treated as `out_of_range` by the sensor fault alerts, so an impossible value cannot quietly switch a rule off. The reading is kept and the row is left out of training. `node_type` is lower-cased and must be 1 to 20 of `a-z 0-9 _ -`, otherwise it is dropped the same way.

**A fault claim stops its sensor only while an alert backs it.** A sensor named in `faults` has its fields stored as null only while an open sensor fault alert exists for it (or an admin marked the sensor as not fitted). A claim with no alert behind it stops nothing: the value is kept, the rules judge it and `quality.not_applied` names the sensors. The firmware's own `not_fitted` list is display only and so is a `warming_up` claim. A node that wants a warming sensor ignored should send the field as null.

**Health fields (all optional).** A node may add these to the same JSON body. A node that sends none of them works as before.

```json
{
  "seq": 1042,
  "boot": 7,
  "up": 3600,
  "ts": 1790000000,
  "faults": { "bme280": "missing", "mpu6050": "stuck" },
  "reset_reason": "poweron",
  "rssi": -61,
  "heap_free": 180000,
  "fw": "2.4.1"
}
```

| Field | Type | Meaning and limits |
| --- | --- | --- |
| `seq` | integer, 0 to 4294967295 | A counter that rises by one per post. A jump means posts were lost and is added to `lost_posts` |
| `boot` | integer, 0 or more | Boot count kept by the node. A rise is a restart. Three restarts in ten minutes raise a monitoring alert |
| `up` | integer seconds | Uptime |
| `ts` | integer Unix seconds, 2001 to 2100 | The node's own clock, sent only once it is set. Stored as `device_ts` beside the server's `recorded_at` and never used to order readings |
| `faults` | object | Sensor key to state for each sensor that cannot be trusted. Empty or absent when all is well. At most 16 entries and keys are cut to 32 characters. A state of `ok` is dropped. A state other than `missing`, `stuck`, `out_of_range`, `rate`, `stale`, `intermittent`, `disagree`, `warming_up`, `not_fitted`, `unplugged` (an analogue input reading zero), `line_low`, `silent`, `garbage` (a serial link delivering lines that fail their checksum) or `one_way` (a satellite that sends but does not answer) is stored as `unknown` |
| `reset_reason` | string, 40 characters at most | Why the node last restarted |
| `rssi` | integer dBm, -127 to 20 | Wi-Fi signal strength |
| `heap_free` | integer bytes | Free heap |
| `fw` | string, 50 characters at most | Firmware version the node is running. It is kept in the health record and does not change the firmware target set on the device |

A health field outside these limits or malformed (a string where a number belongs, a `faults` value that is not an object, a string with a control character such as a NUL or a character that cannot be encoded as UTF-8) never costs the reading. A fault key that cannot be stored is left out of the map and the rest of the map is kept. The field is dropped and the reading is stored. The row's `quality` names what was dropped, as `{"dropped_health": ["rssi"]}` and the count on the device's `health.dropped_fields` goes up. A post that carries only bad health fields leaves the latest vitals and faults as they were. A sensor value keeps its strict validation: a value that is not a finite number still answers `422`. An unknown extra field is ignored as before.

**Sensor keys** for `faults` and the fields each one stops: `bme280` (`temperature`, `humidity`, `pressure`), `mpu6050` (`vibration_x`, `vibration_y`, `vibration_z`, `gyro_x`, `gyro_y`, `gyro_z`), `ina219` (`bus_voltage`, `current_ma`, `power_mw`), `mlx90614` (`ir_temperature`), `vl53l0x` (`distance_mm`), `mq2` (`gas_level`, `gas_alert`), `as5600` (`shaft_angle`, `shaft_rpm`), `max4466` (`sound_level`), `ldr` (`light_level`), `ds18b20` (`contact_temp`), `fc28` (`moisture_level`, `water_detected`, except that `unplugged` stops `moisture_level` only), `nano_bme280` (`nano_temp`, `nano_hum`, `nano_pres`) and `stm32_mpu6050` (`fft_peak_hz`, `vib_magnitude`, `vib_rms_x`, `vib_rms_y`, `vib_rms_z`, `vib_peak`, `stm32_vib_x`, `stm32_vib_y`, `stm32_vib_z`, `vib_clipping`). The two serial links stop every value that arrives over them: `nano_link` stops `nano_temp`, `nano_hum`, `nano_pres`, `nano_light`, `nano_moist` and `nano_water` and `stm32_link` stops the same nine fields as `stm32_mpu6050`. `nano_supply` and `supply` are known keys that stop no field. `stm32` is accepted as an alias of `stm32_link` and stored under that name. A key that is not in this list is stored and stops nothing.

**Revised board keys.** The hub's revised board adds eight keys to `faults`. They stop no field. `expander` is the port expander: `missing` when it does not answer or the bus is stuck, `out_of_range` when a register read back differs from what the hub wrote and `stale` when the driver was never started. `aux_rail` is the 5 V AUX rail, `feed1_rail`, `feed2_rail` and `feed3_rail` are the three 12 V feeds, `sens_rail` is the switched sensor rail, `strip_rail` is the LED strip rail and `enable_rail` is the relay 5 V rail. For a rail, `missing` means its input says the rail is not up, `intermittent` means the input keeps changing so the rail may sit near its switching point and `stale` means the node cannot say, because the expander is not running and trusted, the rail has not been read yet, the last good reading is older than 2 seconds or (for `sens_rail`) the input reads high and no sensor on the rail has answered lately. A rail that is not named was read up from a fresh reading. Silence never means up. Up does not mean in range: the `supply` and `ina219` readings tell that. A hub that does not have the expander never sends these keys.

**Water.** An unplugged moisture input reads the same on this circuit as a probe flooded with a conductive liquid, so the leak alarm must win. `fc28: unplugged` stops `moisture_level` only: `water_detected` is kept, stored and still fires its rule. Any other state of `fc28` stops both fields. The table of partial states in `sensor_map.py` is general, so another key can be given one the same way.

**Clipping.** `vib_clipping` (true or false) is sent by the vibration node when a sample in the window reached the sensor's limit. It is a reading and not a fault: it never nulls the vibration fields. It is stored, returned, ORed in bucketed reads and exported. While it is true the device has one machine-category warning, "<name>: vibration is beyond the sensor's range" (`kind` `clipping`), which resolves after a minute without it. The state `intermittent` is an ordinary fault state like the others: nothing treats it specially.

**Satellite values.** The hub also forwards the Arduino Nano's `nano_temp` (degC, -40 to 85), `nano_hum` (per cent, 0 to 100), `nano_pres` (hPa, 300 to 1100), `nano_light` and `nano_moist` (ADC counts, 0 to 1023) and `nano_water` (true or false) and the Black Pill's `vib_rms_x`, `vib_rms_y`, `vib_rms_z` (g, 0 to 16, the root mean square of each axis with the mean removed), `vib_peak` (g, 0 to 32, the largest sample of the alternating part) and `stm32_vib_x`, `stm32_vib_y`, `stm32_vib_z` (g, -16 to 16, the axis means). Each range is what the part cannot exceed: the Nano's converter is 10 bit, the BME280 compensates inside its data sheet range and the MPU6050 never passes its 16 g full scale. A value outside its range is dropped (stored as null) and the reading is kept, which `quality.dropped_values` names. A value that is not a finite number still answers `422`.

**Links.** The hub may add a `links` object with one entry per serial link (`nano`, `stm32`, at most four, names up to 16 characters): `{"nano": {"ok": 1042, "crc": 0, "gaps": 0, "restarts": 0, "st": 0, "up": 5210, "vcc": 4980}}`. `ok`, `crc`, `fmt`, `gaps` and `restarts` are counters since the hub booted (0 to 4294967295): good lines, lines that failed their checksum, lines refused for their format or length, lines lost and satellite restarts. `st`, `up` and `vcc` are left out until a line has arrived and while the link is dead. `st` is the satellite's status mask (0 to 65535), `up` its uptime in seconds and `vcc` its supply in millivolts (0 to 65535). A bad value is dropped from its entry, a link that is not an object is dropped and `links` is named in `quality.dropped_health`. The latest `links` come back in `health`. At most as many `faults` entries are kept as there are sensor keys plus 16.

**What a fault does.** A sensor named in `faults` is not trusted for that post. Every field it produces is stored as `null`, no alert rule on those fields fires and the anomaly model does not score the row. The value the node sent is kept in the row's `quality`. A fault never raises a machine alert.

**What the model does with missing readings.** A reading is scored only when it carries every feature its model needs. Otherwise `anomaly_score` is `null` and `is_anomaly` is `false`: the reading counts as neither normal nor anomalous. The anomaly alert uses only scored readings and a reading that was not scored is not evidence either way. Training leaves out readings with a missing feature.

**Hub fields.** `diag` is an object of the hub's bench counters (post counters, bodies replaced, `bodyTooBig`, stack high-water marks, lowest free heap, largest free block): at most 16 keys, each a name of up to 24 letters, digits and underscores that starts with a letter, with a whole-number value from 0 to 4294967295. An entry that does not fit is dropped (the rest is kept) and `diag` is named in `quality.dropped_health`. The latest `diag` comes back in `health`. `board_mismatch` (true or false) says the firmware image was built for another board: while it is true the device has one monitoring alert, "<name>: the firmware image does not match this board" (`kind` `board_mismatch`), which resolves on the first health post that does not say so. `not_fitted` is a list of sensor keys the firmware was built without, posted once per boot: only keys in the sensor map are kept (an alias is stored under its name) and the last list is kept when a post leaves it out. A fault on such a key raises no alert and is shown as not fitted and the keys are returned apart from the admin's own list (see the device read).

**Limits.** A device may post at most 60 times a minute (twice the 30 a minute of a node at its fastest interval of 2 seconds, so no healthy node meets it). Beyond that the answer is `429` with a `Retry-After` header in seconds, which firmware should treat as "slow down". A `node_type` longer than 20 characters or holding a control character is dropped (the row is scored by the general model) and named in `quality.dropped_values`. A number sent as a string gets the same range check as a number.

**A model that cannot be used.** A reading is always stored. When the model file cannot be loaded or scoring fails, the reading is stored unscored and `quality.scoring_error` says why (for example `the model file could not be loaded (UnpicklingError)`). It is logged once and the no-scored-reading alert then says the model could not be used.

**Response 201:**

```json
{
  "id": "uuid",
  "device_id": "uuid",
  "node_type": "esp32",
  "temperature": null,
  "anomaly_score": null,
  "is_anomaly": false,
  "recorded_at": "2026-04-23T12:00:00Z",
  "seq": 1042,
  "device_ts": "2026-10-21T08:53:20Z",
  "quality": {
    "faults": { "bme280": "missing" },
    "rejected": { "temperature": 180.2 },
    "dropped_health": ["rssi"],
    "dropped_values": ["nano_temp"],
    "scored_by": "general"
  }
}
```

The response also carries every other sensor column. `seq`, `device_ts` and `quality` are `null` when the node sent no health fields or no fault. `quality.rejected` is present only when the node sent a value for a faulted sensor and `quality.dropped_health` only when a health field was dropped, `quality.dropped_values` only when a satellite value was out of range and `quality.scored_by` (`general`) only when the general model scored a node type that has a model of its own, because that model lacked a column the reading did not have. The same three fields come back from the history, latest and export routes.

---

### POST /telemetry/batch

Up to 100 readings from one machine in one request, oldest first, with a result for each. It is for a gateway that drains a backlog. The single-reading route above does not change.

**Auth:** `X-API-Key`, checked exactly as for a single post.

**Request body:** `{"readings": [ <a reading as POST /telemetry takes it>, ... ]}`. One to 100 items. Each item may carry `observed_at`. The body is at most **600,000 bytes** (`413 body_too_large` over that). A front proxy must allow this route that much (a reading is at most about 5.5 kB and usually 1 kB, so 100 readings are about 100 kB and at most 550 kB).

**Answer:** `200` whenever the request itself is acceptable, with the answer for every reading in order:

```json
{
  "results": [
    {"index": 0, "status": 201, "outcome": "stored", "id": "uuid", "backlog": true},
    {"index": 1, "status": 200, "outcome": "duplicate", "detail": "this boot and seq were already accepted"},
    {"index": 2, "status": 409, "outcome": "refused", "code": "replay_stale", "detail": "..."}
  ],
  "stored": 1, "duplicate": 1, "refused": 1
}
```

Every result has `index` (the item's place in the request), `status` and `outcome`. `status` is the number a single post of that reading would have answered, with the same meaning: **201** stored, **200** duplicate (the exact pair last accepted, nothing stored), **409** or **422** refused. `outcome` says the same in a word (`stored`, `duplicate`, `refused`). A stored item carries the new reading's `id` and `backlog`. A refusal carries a stable `code` (`replay_stale`, `replay_pair_missing`, `counter_out_of_range`, `observed_at_too_old`, `invalid_reading`, `storage_error`) and a `detail` sentence. A duplicate carries `detail` and no `code`. A refusal is never fixed by sending the same item again: a client does not retry a 409 or a 422. One item that fails never fails the others and `results` is in the order of the request.

**The same rules as a single post, per item.** The replay rule (`boot` and `seq`) is judged for each item in order against what the item before it left, all under one lock on the machine, so a batch sent twice answers `duplicate` for its last pair and `replay_stale` for the rest and nothing is stored twice. Physical ranges, the fault-claim rule (a claim stops a sensor only while an alert backs it) and the hashed key apply to every item. A bad item (wrong type, too old an `observed_at`) is that item's `refused`.

**Judged once.** Backlog items are never judged (see `observed_at`). If the batch also carries live readings, the rules and the anomaly window are asked once, for the batch, about the newest live reading, so a batch never queues a flood of alerts or notifications. The repeat windows and the daily caps apply as always.

**Allowance.** It is counted in readings, apart from the single route's 60 a minute: **1,200 readings a minute for one device** (twelve full batches) and **6,000 a minute for the whole site**. A machine whose four nodes post every 5 seconds makes 48 readings a minute, so an hour's outage is 2,880 readings and clears in 2.4 minutes of allowance and a day (69,120) in 58 minutes. If every hub drains at once the site allowance shares out and fifty hubs get 120 a minute each, so an hour's backlog then takes 24 minutes. Over the allowance the answer is `429 device_rate_limited` with `Retry-After` and the `X-RateLimit-*` headers and nothing in the batch is stored. A client that gets it waits the `Retry-After` and sends the same batch again.

---

### GET /telemetry/{device_id}

Returns paginated telemetry for a device.

**Auth:** Bearer JWT, subject to the machine rule below

**Machine rule:** admins and viewers read every machine. Technicians read their own and unowned machines. A machine a technician may not read answers `404 Device not found`, exactly as an id that does not exist does, so the API does not reveal which ids are real. `GET /devices/{id}` answers the same way. A caller who may read a machine but not change it (a viewer) gets `403 Access denied` on a write.

**Query params:** `from` and `to` (ISO datetimes, UTC when no zone is given. `from_ts` and `to_ts` are the older names and still work), `node_type`, `limit` (default 100, at most 5000), `offset` (at most 100,000, `skip` is the older name), `before` and `bucket` (integer seconds, 10 to 86400). With `bucket` the route returns one summarised row per time bucket instead of raw rows, needs `from` and ignores `limit`, `offset` and `before`.

**Order and keyset paging.** Newest first, ending in the reading's id, so two readings stamped alike never swap between pages. `before=<ISO time>,<id>` returns the readings after that one in the same order, straight off an index however far back. A full page carries the cursor of its last row in `X-Next-Before`: send it back as `before` until a page comes back short. A client that wants a whole history walks it this way. Offset is for small reads.

**No `X-Total-Count` on this list, on purpose.** A machine at a reading every 5 seconds holds millions of rows and counting them costs more than the page does, for a number nobody needs to read to walk the list. A client uses `X-Next-Before` (a short page is the end) and, to show how much data there is, the `bucket` summary, whose size is known from the window.

#### Bucketed history (`?bucket=SECONDS`)

A node sends a reading every 5 seconds, so a week is about 120,000 rows. With `bucket` the database summarises them and we return one row per bucket, newest first. A bucket with no readings is left out, so a gap in the data shows as a gap.

Each row carries `device_id`, `recorded_at` (the start of the bucket), `reading_count` and every sensor field. `reading_count` is the number of rows (posts) in the bucket. It is not a count per column: when several node types report for one machine a given column may come from only some of those rows. We choose the aggregate by what the reading means:

| Columns | Aggregate | Why |
| --- | --- | --- |
| `temperature`, `humidity`, `pressure`, `bus_voltage`, `current_ma`, `power_mw`, `ir_temperature`, `distance_mm`, `gas_level`, `shaft_rpm`, `sound_level`, `light_level`, `contact_temp`, `moisture_level` | Mean | The typical level is what a long chart should show |
| `shaft_angle` | Circular mean in degrees, 0 up to 360 | The angle wraps, so readings of 359 and 1 average to 0 and not 180 |
| `vibration_x`, `vibration_y`, `vibration_z`, `gyro_x`, `gyro_y`, `gyro_z` | Mean, plus a peak in `vibration_x_peak` and so on (largest absolute value) | These axes are signed, so their mean is only the static offset and hides the vibration |
| `anomaly_score`, `vib_magnitude` | Maximum | A short spike is what an average would hide |
| `fft_peak_hz` | The frequency of the reading with the strongest vibration (largest `vib_magnitude`) in the bucket | The highest frequency in a bucket is not the frequency of the strongest vibration. Readings with no frequency are skipped |
| `gas_alert`, `water_detected`, `is_anomaly` | Logical OR | One raised alarm marks the whole bucket. `is_anomaly` is false when no reading in the bucket carried it |

A column with no readings in the bucket is `null`. The row has no `id` and no `node_type`.

**Buckets and time zones:** buckets align to the Unix epoch in UTC, so a 300 second bucket always starts on a five minute mark whatever `from` is. The first and last buckets can be partial. The first bucket's `recorded_at` can be earlier than `from_ts`. A `from_ts` or `to_ts` without a time zone is read as UTC. Any other offset is honoured.

**Limits:** `bucket` is 10 to 86400 seconds. `from` is required, `to` defaults to now and the window may span at most 31 days. A window may be at most 999 bucket widths long, so that it touches at most 1000 buckets. A query that runs longer than 5 seconds is cancelled and answers 503. `limit` and `offset` are ignored.

**Errors:** 422 when `bucket` is outside its range, when `from` is missing, when the window is longer than 31 days or when it is longer than 999 bucket widths. The message says what to change: a larger bucket or a shorter window. Without `bucket` the route behaves as before, except that `limit` may be at most 5000 (422 beyond it).

**Example:** `GET /telemetry/{device_id}?bucket=300&from=2026-11-21T14:00:00Z&to=2026-11-22T14:00:00Z` returns up to 289 rows.

---

### GET /telemetry/{device_id}/latest

Returns the single most recent reading for a device.

**Auth:** Bearer JWT, with the same machine rule as `GET /telemetry/{device_id}`

---

### GET /telemetry/export

Stream telemetry for a device as a CSV file, oldest first. Rows are read and sent in batches, so a large export does not sit in memory.

**Auth:** Bearer JWT, with the same machine rule as `GET /telemetry/{device_id}`

**Query params:** `device_id` (required), `from` (ISO datetime, required) and `to` (ISO datetime, defaults to now), UTC when no zone is given. `from_ts` and `to_ts` are the older names, still accepted and deprecated. The span may be at most 31 days: a longer one answers 422 and asks for a shorter range. At most 6 exports a minute per person, 2 at once and 6 in total. Rows are sent oldest first.

**Response:** `text/csv` with `Content-Disposition: attachment`

---

## Retrying a write

A client that timed out cannot tell whether a create happened. Send an `Idempotency-Key` header (8 to 128 visible characters, for example a random UUID) with a create and a repeat of the same request gets the first answer back with `Idempotent-Replayed: true` and creates nothing. It is accepted by `POST /devices`, `/tickets`, `/alert-rules`, `/webhooks` and `/maintenance-windows`. The answer is kept 24 hours, per signed-in account and route, in Redis (process memory when Redis is down). A stored answer can hold a device key or a webhook secret, which are shown once, so it is encrypted with a key derived for this purpose. A repeat with a different body answers `422 idempotency_key_reused`. A repeat while the first is still being handled answers `409 idempotency_in_progress` with `Retry-After`. A failed create is never kept, so it may be tried again with the same key.

| Write | Safe to repeat? | A client that timed out should |
| --- | --- | --- |
| `POST /telemetry` and each item of a batch, with `boot` and `seq` | Yes: the answer is `duplicate` | Send the same body again |
| `POST /telemetry` without the pair | No: a second reading | Send the pair |
| `POST /devices`, `/tickets`, `/alert-rules`, `/webhooks`, `/maintenance-windows` | With an `Idempotency-Key`, yes. Without, no | Send the same body with the same key |
| `PATCH`, `PUT`, `DELETE`, `resolve`, `accept-counter`, firmware upload | Yes (a second DELETE answers 404) | Send it again |
| `POST /devices/{id}/rotate-key`, `/webhooks/{id}/rotate-secret` | No: the old one has stopped and the answer is gone | Rotate again |

---

## Devices

### GET /devices

List all registered devices. Supports tag-based filtering.

**Auth:** Bearer JWT

**Query params:** `limit` (default 50, at most 200), `offset` (`skip` is the older name), `name` (the machine's name, an exact match that ignores case), `search` (a contains match on the name that ignores case, so `search=pump` finds "Pump 1" and "Old pump"), `status` (`online`, `offline`, `warning` or `fault`), `link_state` (`online`, `late` or `offline`) and `tag`. Newest first, ending in id. A tool that knows a name uses `name` and gets at most the machines called that, without paging through the fleet.

**Response header:** `X-Total-Count` is the number of devices that match the filters and the caller's access, ignoring `skip` and `limit`. It is exposed through CORS, so a browser page can read it.

Every device (here, in `GET /devices/{id}` and in `POST /devices`) carries `owner_name`, the owner's name or `null` for an unowned machine. Only the name is returned, because only admins can list users. The reply shape is otherwise unchanged.

Each device carries its link state and its latest health, as `GET /devices/{id}` does (see below).

---

### POST /devices

Register a new device. Returns generated API key. An `owner_id` must be the id of an existing user, otherwise `404 Owner not found`.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "name": "Workshop Node 1",
  "location": "Workshop Bay A",
  "type": "esp32"
}
```

---

### GET /devices/{id}

Get a single device with latest status.

**Auth:** Bearer JWT. A technician asking for a device they may not read gets `404`, the same as for an id that does not exist.

Besides the existing fields (`status`, `last_seen` and the rest) the device carries:

| Field | Meaning |
| --- | --- |
| `not_fitted` | Sensor keys an admin marked as not expected on this machine. Empty by default |
| `not_fitted_by_firmware` | Sensor keys the hub's firmware says it was built without, as it last reported them. Kept apart from `not_fitted`. A fault on a key in either list is shown as `not_fitted` in `health.faults`, raises no alert and does not make the machine unknown |
| `link_state` | `online`, `late` or `offline`, from the age of the last post. See the table below |
| `expected_interval_s` | How often the node posts, in seconds (default 5). The thresholds scale with it |
| `seconds_since_last_post` | Whole seconds since the last post. `null` for a device that has never posted |
| `health` | The latest vitals and faults the node reported or `null` for a node that has never sent a health field |
| `model` | The anomaly model's state for this machine: `state` (`ready`, `learning`, `legacy`, `none` or `error`), `scope` (`machine`, `node_type`, `general` or null), `monitored` (false when no model scores it) and `reason` (why not, in words), `hours_collected`, `hours_needed`, `false_alerts_per_week` (on the newest held-back readings) and `false_alerts_per_week_high_95` (its 95 per cent upper bound), `ambient` (how its own model uses the room or that it has no ambient reference), `light` (its own model has no forest), `trained_at` and `refusal` and `refused_at` (the message and the time of the last retrain that refused this machine's own model, else `null`). A machine in `learning` is not scored and cannot raise an anomaly alert. Read from the loaded model, so a list costs no query per machine |

| Link state | Last post is | What happens |
| --- | --- | --- |
| `online` | At most 4 expected intervals old (20 s by default) | Nothing |
| `late` | Older than 4 intervals | Shown only. `status` stays `online` |
| `offline` | Older than 12 intervals (60 s by default) | `status` becomes `offline`. After 2 minutes one monitoring alert opens |

A post sets `link_state` to `online` at once. A sweep that runs every 15 seconds moves it on, so `late` and `offline` can show up to 15 seconds after the threshold. `status` keeps its two older values and follows the link: it is `online` for `online` and `late` and `offline` for `offline`. A device that has never posted stays `offline` and raises no alert.

```json
{
  "link_state": "online",
  "expected_interval_s": 5,
  "seconds_since_last_post": 3,
  "health": {
    "boot_count": 7,
    "uptime_s": 3600,
    "reset_reason": "poweron",
    "rssi": -61,
    "heap_free": 180000,
    "firmware_version": "2.4.1",
    "last_seq": 1042,
    "reported_at": "2026-04-23T12:00:00Z",
    "faults": { "bme280": "missing" },
    "lost_posts": 3,
    "last_gap_at": "2026-04-23T11:40:00Z",
    "dropped_fields": 0,
    "diag": { "posts": 1200, "bodyTooBig": 0, "minHeap": 98000 },
    "board_mismatch": false,
    "links": {
      "nano": { "ok": 1042, "crc": 0, "gaps": 0, "restarts": 0, "st": 0, "up": 5210, "vcc": 4980 }
    },
    "rules_cannot_evaluate": [
      {
        "rule_id": "uuid",
        "metric": "temperature",
        "sensor_key": "bme280",
        "state": "missing",
        "reason": "sensor bme280 is not answering, so temperature is not measured"
      }
    ],
    "reset_loop": false
  }
}
```

`health.server_faults` ({sensor key: state}) sits beside `health.faults` and lists what the server found for itself in the latest post: `out_of_range` for a value outside what the part can measure and `stuck` for a continuous value that has stopped moving for longer than its table period. They raise the same sensor fault alerts as a fault the node reports. A stuck value is flagged and kept: it is not hidden from the rules or the model.

A vital the node did not send in its latest post keeps its last value, so `reported_at` says when any health field last arrived. `faults` is replaced by every post that carries a health field and an absent one means no fault. `links` are the latest serial link counters the hub sent. `rules_cannot_evaluate` lists the threshold rules that cannot fire now because the sensor that produces their field is faulted or not fitted (`state` is the fault state or `not_fitted`) and the cause is the sensor alert. A fault on a sensor listed in the device's `not_fitted` is shown in `faults` as `not_fitted`. `lost_posts` counts posts missed to gaps in `seq`, `dropped_fields` counts health fields that were dropped as unusable and `reset_loop` is `true` while the node has restarted three times in ten minutes. The same `link_state`, `expected_interval_s` and `seconds_since_last_post` come back from the other device routes, with `health` filled only by the two reads above.

---

### PATCH /devices/{id}

Update a device. Send only the fields to change.

**Auth:** Bearer JWT (an admin or a technician for their own or unassigned devices). A device a technician may not read answers `404`. A viewer gets `403`.

| Field | Who may send it |
| --- | --- |
| `name`, `location`, `status` | An admin or a technician for their own or unassigned devices |
| `owner_id`, `tags`, `firmware_version`, `not_fitted`, `expected_interval_s` | Admins only. A technician who sends one gets `403` with a message naming the field |

`expected_interval_s` (1 to 86400, default 5) is how often the node posts. The liveness thresholds follow it (late after 4 intervals, offline after 12). The anomaly alert's windows follow the interval the readings themselves show, within a quarter and twenty times this one, so a record that is out of date does not blind the alert. `not_fitted` is a list of sensor keys (see the telemetry section) that are not expected on this machine, for example a hub with no Black Pill: `["stm32_link", "stm32_mpu6050"]`. The default is an empty list. A fault reported for a listed key raises no alert and `health.faults` shows it as `not_fitted`. An unknown key answers `422` and an alias such as `stm32` is stored under its name.

`owner_id` must be the id of an existing user, otherwise `404 Owner not found`. Sending `"owner_id": null` clears the owner, which makes the machine shared. Leaving the field out keeps it. A null in any other field is ignored.

---

### POST /devices/{id}/rotate-key

Replace the device's API key. The response includes the new key, so the old one stops working straight away and the firmware needs the new value. A key is stored only as a keyed hash, so this response (and the one from `POST /devices`) is the only time a key can be seen. No other route or export returns one.

**Auth:** Bearer JWT with fresh proof: the caller's password (or two-step code) goes in the request body as `{"password": "..."}`, as for the other dangerous actions (`400 proof_required` when it is missing, `400 proof_wrong` when it is wrong). Only a signed-in session can do it, not an API token. An admin may and so may the machine's owner. A technician who only shares an unowned machine gets `403 key_rotation_forbidden`.

---

### POST /devices/{id}/accept-counter

Accept a new `(boot, seq)` counter for a machine whose flash was wiped. A machine that has sent the pair must always send a newer one (see Replay protection under `POST /telemetry`), so a hub that restarts its boot count at 1 is refused with `409` until this is done. It forgets the last pair, sets `replay_refused` to 0 and writes an audit entry (`replay_counter_accepted`, with the previous pair). The machine must still send the pair and its next post sets the new start.

**Auth:** Bearer JWT (Admin only)

**Response:** the machine, as `GET /devices/{id}` returns it.

---

### DELETE /devices/{id}

Remove device and cascade-delete its telemetry and rules.

**Auth:** Bearer JWT (Admin only)

---

### POST /devices/{device_id}/tags

Add a tag to a device.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{ "tag": "pump-room" }
```

---

### DELETE /devices/{device_id}/tags/{tag}

Remove a specific tag from a device. Answers `200` with the device (not 204, so a page can show the new tag list). Adding a tag (`POST /devices/{device_id}/tags`) answers `201` with the device.

**Auth:** Bearer JWT (Admin only)

---

### POST /devices/batch/firmware-update

Trigger an OTA firmware update for all devices matching a given tag.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "tag": "pump-room",
  "version": "v1.4.2"
}
```

**Response 202:**

```json
{ "queued": 3, "tag": "pump-room", "target_version": "2.5.0" }
```

---

## Alert Rules

### GET /alert-metrics

Also carries `daily_limits` for every signed-in role: for `email` and `sms`, the daily `limit`, today's `count`, whether it is `reached` and `resets_at` (00:00 UTC, with a `Z`). Once a limit is reached no more of that channel are sent until it resets, so this is how an operator sees that messages have stopped. It carries no recipient and no address.

The readings a rule may watch, the conditions and the severities, from the same lists the rule routes check, so the rule form and the backend cannot drift.

**Auth:** Bearer JWT

```json
{
  "metrics": [{ "key": "anomaly_score", "type": "number" }, { "key": "gas_alert", "type": "boolean" }],
  "conditions": ["gt", "lt", "eq"],
  "severities": ["info", "warning", "critical"]
}
```

`metrics` holds every reading field a post can carry (not the node's health fields, which never reach a rule and not `node_type`) and `anomaly_score`, the score the model gave the reading. A rule on the score does not fire for a reading that was not scored. A boolean is compared with 1 for true and 0 for false.

---

### GET /alert-rules

List rules, newest first (ending in id), with `X-Total-Count`. **Query params:** `device_id` (a machine the caller may not read answers `404`), `metric` (one of `GET /alert-metrics`, else `422`), `from` and `to` (when the rule was made), `limit` (default 50, at most 200) and `offset`.

**Auth:** Bearer JWT

### GET /alert-rules/{id}

One rule. A rule on a machine the caller may not read answers `404 rule_not_found`.

---

### POST /alert-rules

Create a threshold rule for a device metric. `metric`, `condition` and `severity` must be one of the values `GET /alert-metrics` returns, otherwise `422`, because a rule on anything else could never fire. An unknown `device_id` answers `404`. The same check applies to `PUT /alert-rules/{id}`. A rule saved before the check existed can still be listed.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "device_id": "uuid",
  "metric": "temperature",
  "condition": "gt",
  "threshold": 80.0,
  "severity": "critical",
  "for_seconds": 30,
  "clear_margin": 2.0
}
```

`for_seconds` (0 to 86400) is how long the condition must hold before the alert is raised and the value must also be back inside the limit for this long and at least 60 seconds, before it resolves. `null` or left out means the default for the metric: 30 for a number and 0 for an on-or-off reading (`gas_alert`, `water_detected`, `nano_water`, `vib_clipping`), which raises at once. `clear_margin` (0 or more) is how far back inside the limit a number must come before the alert can resolve. `null` means 2 per cent of the threshold and never less than one unit of its last decimal place (80.0 gives 1.6). An equality rule does not use it. A rule comes back with `for_seconds` and `clear_margin` as stored and `effective_for_seconds` and `effective_clear_margin` as used. In `PUT /alert-rules/{id}` a field left out is kept and an explicit `null` for `for_seconds` or `clear_margin` goes back to the default.

---

### PATCH /alert-rules/{id}

Update a rule. A field left out is kept. `for_seconds` and `clear_margin` may be set to `null`, which puts back their default. Any other `null` answers `422 validation_failed`. `PUT /alert-rules/{id}` still works as an alias for this release (it always merged like a PATCH) and answers with `Deprecation` and `Sunset` headers.

**Auth:** Bearer JWT (Admin only)

---

### DELETE /alert-rules/{id}

Delete an alert rule.

**Auth:** Bearer JWT (Admin only)

---

## Alerts

### GET /alerts

List alerts. Filter by `resolved=false` for active alerts and by `category` (`machine` or `monitoring`, anything else answers `422`). A technician receives only the alerts of machines they may read (their own and unowned).

**Auth:** Bearer JWT

**Query params:** `device_id` (one machine: a machine the caller may not read answers `404`), `resolved`, `category`, `kind` (`rule`, `anomaly`, `offline`, `reset_loop`, `unscored`, `sensor`, `clipping`, `board_mismatch`, `unmonitored` or `model_move`), `severity` (`info`, `warning` or `critical`), `from` and `to` (when the alert was raised, UTC when no zone is given), `limit` (default 100, 1 to 500), `offset` (default 0, at most 100,000, `skip` is the older name) and `before`. A value outside the allowed set answers `422 invalid_filter`. The order is newest first and ends in the alert's id, so two alerts raised in the same instant never swap between pages.

**Keyset paging.** `before=<ISO time>,<id>` returns the alerts after that one in the same order, read straight off an index however far back. A full page carries the cursor of its last alert in `X-Next-Before`: send it back as `before` until a page comes back short. Offset is for small lists.

**Response header:** `X-Total-Count` is the number of alerts that match the filters and the caller's access, ignoring `limit` and `offset`. A page asked for with `before` carries no total (counting for every page of a long walk is what keyset paging avoids). `X-Next-Before` is described above.

Each alert carries `category`, `sensor_key` and `kind` beside its existing fields. `kind` is `rule` for a threshold rule's alert, `anomaly` for the model's and `sensor`, `offline`, `reset_loop`, `unscored`, `clipping`, `board_mismatch`, `unmonitored` or `model_move` for the others the system raised. Older rows have `null`. The database holds at most one open alert of a kind for a device (and a sensor), so two posts at once cannot leave a duplicate. `category` is `machine` for an alert about the machine (a rule or the anomaly model) and `monitoring` for an alert about how it is watched. `sensor_key` names the sensor a monitoring alert is about and is `null` otherwise. The monitoring alerts below all have severity `warning` and `rule_id` null:

- `Anomaly detected on <name>: <reason>`: the model's alert (`kind` `anomaly`), one open per machine. The reason always names a sensor, for example `temperature is well above this machine's usual range. 9 of 12 scored readings in the last 120 s were at or over the anomaly limit of 0.70 (median 0.91)` or `temperature has run roughly 2.4 °C above what this machine normally shows for this load, on average over about the last 35 minutes. ...`. The offset and the minutes are approximate: the offset is the average over the run so far and the minutes count from when the evidence began to build. When only the combination of readings is unusual the reason says so and names the sensor furthest from its usual value. It resolves only after a calm of 30 minutes (or 120 intervals, the longer), so a fault that comes and goes keeps one alert open. A new warning waits 15 minutes after a resolve and a critical one 5 minutes. Its message then ends `(resolved: <reason>)`. `evidence` carries the figures. Readings taken in a maintenance window are left out of its decision.
- `Not monitored by the anomaly model: <reason>` (`kind` `unmonitored`) and `Anomaly model needs a person: <reason>` (`kind` `model_move`): raised by a retrain for a machine left with no working model and for one whose new model would move its normal too far (see `POST /ml/retrain`). They resolve at the first retrain that gives the machine a working model.
- `<name>: sensor <key> is <state in words> (<state>)`: one per device and sensor, with `sensor_key` set. It opens once the same fault has been reported without a break for 60 seconds and its message is updated when the state changes, never duplicated. It resolves itself when the sensor has reported ok or left the `faults` map for 60 seconds and its message then ends with `(resolved: the sensor has reported ok for a minute)`. A sensor that changes between ok and a fault more than five times in an hour gets one alert at once whose message says `is intermittent (it changed between working and faulty 7 times in the last hour)` and it stays until the changes have aged out of the hour. `warming_up`, `not_fitted` and a key in the device's `not_fitted` list raise nothing.
- `<name> has had no scored reading for 10 minutes: the model is missing <inputs>`: opened when a node that keeps posting has had no scored reading for 10 minutes, which names the model inputs its readings lack. It covers a faulted sensor and also a field that goes missing with no fault named. It resolves with the next scored reading.
- `<name> has not reported for 2 minutes`: opened once when a node has been silent for 2 minutes. It resolves itself when the node posts again and its message then ends with `(back online after 7 min 30 s)`. A device already silent for over a day raises no new alert, judged by the real age of its last post, so an API restart never reopens or closes one.
- `<name> has restarted 3 times in 10 minutes`: opened once when the `boot` counter shows three restarts inside ten minutes. Only restarts seen inside the window count, so a counter that jumped while the node was away is one restart dated by `up`. It resolves itself ten minutes after the last restart.

**Rule alerts are stateful.** A rule alert is one row for as long as its condition lasts, not one row for every breaching reading. There is at most one open alert for a machine and a rule, so two rules on one machine each have their own. It carries:

| Field | Meaning |
| --- | --- |
| `occurrences` | How many readings met the condition, counting the readings of the hold that came before the alert was raised |
| `last_value` | The value of the latest reading that met it |
| `peak_value` | The most extreme value, from the first reading of the hold onwards: the highest for `gt` and `eq`, the lowest for `lt`. For the model's alert, the highest score |
| `first_seen_at` | When the condition first began to hold, which is about `for_seconds` earlier than `triggered_at`. Null on system alerts and on rule alerts from before migration 031 |
| `evidence` | The figures behind a model alert, null on every other alert. **Range form:** `readings`, `over_boundary`, `median`, `window_s` and, when one sensor carried the score, `sensor`, `value`, `range` (`[low, high]`, the machine's usual range) and `direction` (`above` or `below`). **Drift form** (a sensor that has drifted from where the model expects it): `sensor`, `expected` (the value it should have) and `minutes` (how long it has drifted). A client reads `sensor` to know which form it has |
| `last_seen_at` | When a reading last met the condition. For the model's alert, the latest evaluation |
| `still_occurring` | `true` when `last_seen_at` is within 120 seconds and the alert is open, `false` when it is older or the alert is resolved, `null` for an alert with no `last_seen_at` (the system alerts). The dashboard shows "still occurring" when true and "last seen at ..." when false |

The alert is raised once the condition has held for the rule's `for_seconds` without a gap in the readings (a gap of more than 3 intervals and at least 30 seconds, starts the hold again). While it goes on the one row is updated in place. It resolves by itself when the value has been back inside the limit by the rule's `clear_margin` for `for_seconds` and at least 60 seconds and its message then ends `(resolved: back inside the limit)`. A value between the threshold and the margin neither counts as occurring nor starts the clear hold. People are notified when the alert is raised, when it rises to critical and as a reminder once an hour while it stays open and never for each reading.

When the rule's field is unavailable (the sensor is faulted, the node leaves it out or the node is silent) the open alert stays open but `last_seen_at` stops moving, so `still_occurring` becomes `false`. After an hour with no reading that met the condition it is closed and its message ends `(closed: no reading met the condition for an hour)`. Editing a rule's metric or condition closes its open alert (`(closed: the rule was changed)`) and a new threshold keeps it. Deleting a rule closes its open alert (`(closed: the rule was deleted)`) and the alert stays with `rule_id` null. A ticket made from a rule alert keeps pointing at that one row. If the alert resolves and the breach comes back it is a new row and the ticket keeps its old one. An alert resolved by hand while the condition goes on is not raised again for an hour. Resolved rule alerts are deleted after 12 months like the others, unless a ticket points at them.

A threshold rule whose field is null because its sensor is faulted raises no alert of its own: the sensor alert covers the cause and the rule is listed in the device's `health.rules_cannot_evaluate`.

Monitoring alerts email as a warning on the hourly window for that device and kind (and for that sensor, for a sensor alert). They never send the critical text message. They are not raised during a maintenance window.

---

### GET /alerts/{alert_id}

One alert. **Auth:** Bearer JWT. An alert on a machine the caller may not read answers `404 alert_not_found`, the same as one that does not exist.

**Removed:** `GET /alerts/{device_id}` (a machine's alerts) is gone, because the two cannot share a path. Use `GET /alerts?device_id=<id>`. A caller that still sends a machine id it may read gets `410 endpoint_removed` that says so.

---

### POST /alerts/{id}/resolve

Mark an alert as resolved. An action is a POST. `PATCH /alerts/{id}/resolve` still works as an alias for this release and answers with `Deprecation: true` and a `Sunset` date.

A system alert (a silent node, a sensor fault, a restart loop, the model alert) resolved by hand while its cause goes on is accepted and its message then ends with "(resolved by hand)". The json webhooks are told (`alert.resolved`).

**Auth:** Bearer JWT (an admin or a technician for alerts on their own or unowned machines). Viewers get `403`. An alert on a machine the caller may not read answers `404`.

---

## Tickets

### GET /tickets

Filters: `status` and `priority` (fixed sets, an unknown value is `422`), `device_id` (the tickets about one machine, found through the ticket's machine or its alert's machine), `alert_id` and `ticket_number` (the ticket's own number, at most one match). Paged with `limit` (default 50, at most 200) and `offset` (`skip` is the older name), newest first and ending in id, with `X-Total-Count`.

List tickets. A technician receives only tickets on machines they may read (their own and unowned), found through the ticket's machine or its alert's machine. A ticket tied to no machine (it may be one whose machine was deleted) is listed for admins and viewers and for a technician only when they raised it or were given it. Admins and viewers see all.

**Auth:** Bearer JWT

**Query params:** `skip` (default 0, at least 0), `limit` (default 20, 1 to 200), `status` (optional: open, in_progress, closed), `priority` (optional: low, medium, high, critical), `alert_id` (optional: only the tickets raised from that alert)

**Response header:** `X-Total-Count` is the number of tickets that match the filters and the caller's access, ignoring `skip` and `limit`.

Every ticket carries `assigned_to_name` and `created_by_name` beside the ids. They are names only and `null` when the ticket has nobody there. The existing fields are unchanged.

---

### GET /tickets/assignees

The people a ticket can be assigned to: admins and technicians, as `[{"id": "uuid", "name": "..."}]`. Never an email or a phone number. A technician cannot list users, so this is how they assign within the team.

**Auth:** Bearer JWT (an admin or a technician). Viewers get `403 Access denied`.

---

### POST /tickets

Create a maintenance ticket, optionally linked to an alert. The `alert_id` is stored and returned. `GET /tickets?alert_id=` finds the ticket again.

**Auth:** Bearer JWT (an admin or a technician for their own or unowned machines or for a ticket tied to no machine). Viewers get `403 Access denied`. A machine the caller may not read answers `404 Device not found`, like one that does not exist. When `alert_id` is given the alert must exist and, with `device_id`, belong to that machine. Otherwise the answer is `404 Alert not found`.

**Request body:**

```json
{
  "device_id": "uuid",
  "alert_id": "uuid or null",
  "title": "High temperature on Workshop Node 1",
  "description": "Temperature exceeded 80C threshold.",
  "priority": "critical"
}
```

**Response:** includes `ticket_number` field (displayed as PHM-0001 format)

---

### GET /tickets/{id}

Get a single ticket with full detail including `ticket_number`.

**Auth:** Bearer JWT. A ticket on a machine the caller may not read answers `404 Ticket not found` and so does a machine-less ticket a technician neither raised nor was given.

---

### PATCH /tickets/{id}

Update ticket status, priority or assignee. Send only the fields to change. An explicit `"assigned_to": null` clears the assignee. Leaving it out keeps it. A new assignee must be an existing user, otherwise `404 Assignee not found`. They must be an admin or a technician who can open the ticket (it is on a machine they may read or it is theirs), otherwise `400 That person cannot be given this ticket`. A null in any other field is ignored.

**Auth:** Bearer JWT (an admin or a technician for tickets on their own or unowned machines or tied to no machine). Viewers get `403 Access denied`. A ticket on a machine the caller may not read answers `404 Ticket not found`.

---

## Auth

### POST /auth/register

Create a new user account. The account is a viewer.

**Availability:** controlled by `REGISTRATION_OPEN`. Unset, registration is open in development and closed everywhere else. When closed it answers `403` with `Registration is closed. Ask an administrator for an invitation.`. A first sign-in with Google, GitHub or Microsoft for an address with no account is refused in the same way. An existing account still signs in and an invited person still joins through `POST /auth/accept-invite`. The first admin is created with `python -m app.scripts.create_admin`.

**Rate limit:** 10/hour per IP

**Request body:**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "password": "securepassword"
}
```

---

### GET /auth/providers

Which sign-in providers are set up, by name only (no client ids or secrets), so the sign-in page can show only the buttons that work. Without a configured provider its route answers `501`.

**Auth:** none

**Rate limit:** 60/minute per IP

**Response 200:**

```json
{ "providers": ["google", "microsoft"] }
```

The list holds any of `google`, `github` and `microsoft`. It is empty when none is configured.

---

### POST /auth/login

Login and receive a short-lived access token. Sets a 7-day httpOnly refresh cookie and, for this account, a signed `kb_<id>` cookie (90 days, httpOnly, path `/api/v1/auth`) that marks this browser as one that has signed in before.

The email is compared in lower case. A password with a NUL character answers `422`. An unknown address, a wrong password, an account with no password and a deactivated account all answer the same `401 Invalid credentials` after the same single password check, so neither the answer nor the time says which addresses have accounts.

**Rate limit:** 5/minute per IP

**Sign-in slowdown.** An account is never locked for good by wrong passwords, because that let anyone who knew an address keep its owner out. Failures are counted per account and source (an IPv6 /64) and per account across every source. An unknown address is counted exactly like a known one.

| What is counted | Window | Threshold | What happens |
| --- | --- | --- | --- |
| Failures for one account from one source | 15 minutes | 5 | That source waits 30 seconds after its last failure, then 60, 120 and so on up to 15 minutes. Answered `429` with `Retry-After`. Other sources are not affected. |
| Failures for one account from every source | 1 hour | 30 | A browser that has not signed in to this account before (no valid `kb_` cookie) may try once every 10 seconds, answered `429` with `Retry-After: 10` otherwise. A known browser is not slowed. Admin accounts are never slowed this way. The owner is emailed once a day at most. |

A person who is being guessed at from many places therefore signs in from a browser they have used before at once and from a new one after at most a few seconds' wait. What a stranger with many addresses can still do is one try every 10 seconds on a non-admin account, which the owner is told about. An admin account relies on the per-source wait, two-step sign-in and the per-address rate limit instead. A wrong password or code on the proof routes counts the same way.

**Request body:**

```json
{
  "email": "jane@example.com",
  "password": "securepassword"
}
```

**Response 200:**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

If the account has 2FA enabled, a correct password does not sign in on its own. The response carries a short-lived challenge instead, no refresh cookie is set and the client completes sign-in with `POST /auth/2fa/verify`:

```json
{
  "access_token": null,
  "token_type": "mfa",
  "mfa_required": true,
  "mfa_token": "eyJ..."
}
```

The `mfa_token` expires after 5 minutes and is accepted only by `POST /auth/2fa/verify`.

**Response 429:** the account is locked after too many failed attempts.

---

### POST /auth/refresh

Exchange the httpOnly refresh cookie for a new 15-minute access token. No request body needed - the cookie is read automatically.

Each sign-in starts a session that the server keeps (table `user_sessions`) and the refresh token names it. **A refresh token works once.** Every successful call answers with a new access token and sets a new refresh cookie and the one just used stops working, except for a grace of 10 seconds (`REFRESH_GRACE_SECONDS`): a token that was swapped moments ago and is presented again, from the same session, gets the same new token back and is not treated as theft. That covers two tabs refreshing together and a retry after a lost reply. The session row is locked while it is rotated, so two refreshes cannot both rotate it. Presenting a token that was swapped more than the grace ago is treated as theft: the whole session is revoked and the call answers `401`, which also stops whoever holds the newer token. The dashboard should keep the cookie the response sets.

A refresh token with no session, a revoked or expired session or one from before sessions existed answers `401 Session is no longer valid` and the person signs in again.

The refresh cookie lasts the lesser of 7 days and what its session has left, so a dead copy never sits in the browser past the end of its session. It is sent only to the two routes that read it. It is set twice, once with path `/api/v1/auth/refresh` and once with `/api/v1/auth/logout`, with the same value and the browser sends each copy to its own route only. The wider `/api/v1/auth` copy an earlier version set is cleared whenever the cookie is set or removed.

**A session has an absolute end.** It stops working `SESSION_MAX_DAYS` (default 30) after it began, however often it is refreshed and a refresh after that answers `401`. The sliding 7 days never carry it past that end.

**Auth:** None (cookie-based)

**Rate limit:** 30/minute per IP

**Response 200:** an access token (its `sid` claim names the session) and a `Set-Cookie` for the new refresh token.

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

---

### GET /auth/sessions

The caller's own live sessions, newest first, so a person can see where they are signed in.

**Auth:** Bearer JWT. **Rate limit:** 30/minute per IP.

**Response 200:**

```json
[
  { "id": "uuid", "label": "Chrome on macOS", "created_at": "ISO datetime", "last_used_at": "ISO datetime", "current": true }
]
```

`current` is true for the session making the call. `label` is a coarse description made from the user agent when the session began ("Edge on Windows", "Safari on iOS" or "Unknown browser"). **No address is shown and none is kept**: a person recognises their own sessions by the browser and the times and an address is personal data that adds little. The raw user agent is not kept either.

---

### DELETE /auth/sessions/{session_id}

End one of the caller's own sessions. Another person's id, an ended one and one that never existed all answer `404 Session not found`. Ending the current session is allowed and the reply then also clears this browser's refresh cookies.

**Auth:** Bearer JWT. **Rate limit:** 20/minute per IP. **Response 204:** no body.

---

### POST /auth/sessions/end-others

Sign out everywhere else. Every other live session of the caller is ended and the session making the call carries on.

**Auth:** Bearer JWT. **Rate limit:** 10/minute per IP.

**Response 200:** `{ "ended": 2 }`

---

### POST /auth/logout

End the session on the server and clear the cookies. When the refresh cookie is valid its session is revoked, so a copy of that refresh token stops working and so does the access token issued with it. Other browsers' sessions are not touched. Signing out everywhere is what a password change or a two-step change does.

It needs only the cookie, so an expired access token never stops someone signing out. A missing or invalid cookie is not an error: the answer is still `204`. Call it before clearing local state, with credentials included, from every sign-out button and after deleting an account.

**Auth:** None (cookie-based)

**Response 204:** no body.

---

### GET /auth/me

Returns the currently authenticated user's profile: `id`, `name`, `email`, `role`, `created_at`, `phone_number`, `oauth_provider`, `totp_enabled` and `has_password`. `has_password` is `false` for an account that signs in through a provider. There is no `permissions` field.

**Auth:** Bearer JWT

---

### PATCH /auth/me

Update the current user's name, email or phone number. Name is at most 100 characters and email 150.

**Changing the email needs proof of ownership**, because it is how the account is found at the next sign-in. Send `current_password` (an account with a password). A provider account cannot change its email at all, since the address comes from the provider.

| Case | Answer |
| --- | --- |
| No password sent | `400` `Enter your current password to change your email` |
| Wrong password | `400` with the same message. It is counted and slowed like a wrong sign-in |
| Provider account | `403` `Your email comes from <Provider> and cannot be changed here` |
| Address already used | `400` `Email already registered` |

**Changing the phone number needs the same proof**, because critical alert texts go to it. Sending the number the account already has or changing only the name, needs none. A provider account proves it with a return from its provider in the last 5 minutes on this session, as for the other proofs. The action text in the error is `change your phone number`.

**Limits.** The route is limited to 20 requests an hour per address. An account may change its email at most 3 times an hour and 5 times a day (`EMAIL_CHANGES_PER_HOUR`, `EMAIL_CHANGES_PER_DAY`), otherwise `429 You have changed your email too many times. Try again later`. The notice to the old address goes only to an address that was never unconfirmed (an invitation went to it or a provider verified it) or that has been the sign-in address for at least an hour. A change to an address typed in by whoever holds the token therefore mails nothing, so the route cannot be used to make the service mail someone.

The proof fields are never stored or returned. Name and phone changes need none. With two-step on, `code` is needed as well as the password.

**What happens after a successful email change.** The change takes effect at once. Every other session of the account is ended, so no browser that signed in with the old address stays signed in. The session that made the change carries on. A plain notice goes to the **old** address saying the sign-in address was changed, when (UTC), to a masked form of the new address (`j***@example.com`) and to contact support and change the password if it was not them. The new address is not confirmed by a link first (see the known limits in docs/security.md).

**Auth:** Bearer JWT

**Rate limit:** 5/hour per IP

**Request body (all fields optional):**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "phone_number": "+447700900000",
  "current_password": "needed only when email changes"
}
```

---

### POST /auth/change-password

Change the current user's password. An account that has no password (it signs in through a provider) answers `400 This account has no password. It signs in through its provider` and the attempt does not count towards the lock. A wrong password counts towards the lock and a right one clears the count. Every other session for the account ends. The response sets a fresh refresh cookie so this browser stays signed in.

**Auth:** Bearer JWT

**Rate limit:** 10/minute per IP

**Response 204:** no body.

**Request body:**

```json
{
  "old_password": "currentpassword",
  "new_password": "newsecurepassword"
}
```

---

### POST /auth/me/phone/send-code

Send a six digit code by text to the number on the account. The code expires after 10 minutes and is stored as a keyed hash. Limits: 10 requests an hour per account route, 5 codes an hour per account and 3 an hour per number (429 with `Retry-After`). 400 when there is no number. 502 when the vendor refused the text. 503 `Texts are not set up on this server, so a confirmation code cannot be sent` in production with no text vendor. In development with no vendor the answer is 200 `{"sent": false}` and the log says a code was issued, with the code only when `LOG_EMAIL_BODIES` is on. A success is `{"sent": true, "detail": "...", "expires_in_seconds": 600}`.

### POST /auth/me/phone/confirm

Body `{"code": "123456"}`, exactly six digits. 204 and `phone_confirmed` becomes true. 400 `That code is wrong or has expired` for a wrong code, an expired one, one made for an earlier number or none pending. Five wrong tries end the code and a new one is needed.

`GET /auth/me` returns `phone_confirmed`. Alert texts go only to a confirmed number. Changing the number through `PATCH /auth/me` makes `phone_confirmed` false and drops any pending code, so the page should offer "Send code" after a number is saved.

### DELETE /auth/me

Delete the signed-in account. The person's tickets stay, with their name taken off both `created_by` and `assigned_to`. The person's entries in the audit log are kept. `GET /auth/me/export` returns them first.

**Auth:** Bearer JWT, plus proof in the request body. Send the one that applies:

| Account | Body |
| --- | --- |
| Has a password | `{"password": "<current password>"}`, plus `"code"` when two-step is on |
| Signs in through a provider, two-step on | `{"code": "<current two-step code>"}` |
| Signs in through a provider, two-step off | no field. The person must have returned from their provider in the last 5 minutes |

`GET /auth/me` returns `has_password`, `totp_enabled`, `oauth_provider` and `provider_signin_recent` so a page knows which to ask for. `provider_signin_recent` is true only for the session that made the provider return, in the last 5 minutes. Another session of the same account, a stolen token included, sees `false` and cannot use it. For a provider account with no two-step the page sends the person through the provider's normal sign-in (`GET /auth/google`, `/github` or `/microsoft`) and when they land back, `provider_signin_recent` is true for 5 minutes and the delete can be sent. A typed word is no longer proof, because a stolen token can type one. `confirm` is accepted and ignored.

**Status codes for a wrong proof.** Every route that checks a proof answers `400` for a wrong or missing one: the delete, the email change, the phone change, `POST /auth/change-password`, `POST /auth/2fa/enable`, `/2fa/confirm`, `/2fa/disable` and `POST /auth/link/{provider}`. `401` is only for a bad, expired or missing token and `429` for a locked account. (`POST /auth/2fa/verify`, the second step of signing in, still answers `401` for a wrong code, because the person is not signed in yet.) A dashboard that renews its token on a `401` and retries must not do so for these routes. A right proof or a successful sign-in clears the wrong-guess count and a count whose lock has run out starts again from zero.

**Exact `400` messages** (the same text for a missing and a wrong value, so nothing is learned from the difference):

| Account | Message |
| --- | --- |
| Has a password | `Enter your current password to delete your account` |
| Provider account, two-step on | `Enter a current two-step code to delete your account` |
| Provider account, two-step off | `Sign in with Google again within the last 5 minutes to delete your account` (the provider's name: Google, GitHub or Microsoft) |

A wrong password or code is counted and slowed like a wrong sign-in (five failures from one place make that place wait, answered `429` with `Retry-After`), so this route cannot be used to guess either. The same holds on `POST /auth/change-password`, `/2fa/enable`, `/2fa/confirm`, `/2fa/disable` and the email change. A request with no body is refused with the message above.

**Refused with `409`:**

- `Hand your machines to another person first` while the person owns any machine. Deleting would leave the machines shared with every technician, so an admin hands them on first with `PATCH /devices/{id}`.
- `This is the last admin. Make another person an admin first` for the only admin.

**Rate limit:** 5/hour

**Response 204:** no body. The refresh cookie is cleared.

---

### GET /auth/me/export

GDPR data export. Returns a JSON file (`Content-Disposition: attachment`) holding everything the service keeps about the current user. It never holds the password hash, the two-step secret or the session version.

**Auth:** Bearer JWT

**Response 200:**

```json
{
  "profile": {
    "id": "uuid", "name": "...", "email": "...", "phone_number": "+447700900000", "role": "technician",
    "created_at": "ISO datetime", "last_login": "ISO datetime or null",
    "sign_in_provider": "github or null", "sign_in_provider_id": "the provider's identifier or null",
    "has_password": true, "two_step_enabled": false,
    "failed_sign_in_attempts": 0, "locked_until": "ISO datetime or null", "permissions": null
  },
  "tickets": [ { "id": "uuid", "ticket_number": 12, "title": "...", "description": "...", "status": "open", "priority": "low",
                 "device_id": "uuid or null", "alert_id": "uuid or null", "created_by_you": true, "assigned_to_you": false,
                 "created_at": "ISO datetime", "updated_at": "ISO datetime" } ],
  "tickets_assigned": [ "same shape or {id, ticket_number, status, text_withheld: true, created_by_you, assigned_to_you} when the person may not read the ticket's machine" ],
  "devices": [ { "id": "uuid", "name": "...", "type": "esp32", "location": "...", "status": "online",
                 "firmware_version": "1.2.3 or null", "created_at": "ISO datetime" } ],
  "maintenance_windows": [ { "id": "uuid", "label": "...", "start_at": "ISO datetime", "end_at": "ISO datetime",
                             "device_id": "uuid or null", "suppress_alerts": true, "created_at": "ISO datetime" } ],
  "audit_log": [ { "action": "ticket_created", "resource": "ticket", "resource_id": "...", "detail": "...", "created_at": "ISO datetime" } ]
}
```

`tickets` are the ones the person raised. `devices` are the machines they own. `maintenance_windows` are the ones they created. `audit_log` holds only their own entries. A ticket's other party is not named: only `created_by_you` and `assigned_to_you` say whether it was this person. A ticket assigned to someone who may not read its machine carries its number and status but not its text. If the log entries cannot be read the whole export answers `500` rather than returning an incomplete file. `permissions` is a stored field that nothing reads (see below).

---

### POST /auth/link/{provider}

Link Google or GitHub to the signed-in account when it has a password, so the person can then sign in either way. `provider` is `google` or `github`. Microsoft cannot be linked, because a Microsoft address is not verified.

**Proof is checked first:** `{"password": "..."}`, plus `"code"` when two-step is on. A wrong one answers `400` (`Enter your current password to link Google` or `Enter a current two-step code to link Google`) and counts towards the sign-in lock. Other answers: `400` for an account that already signs in through its provider or for Microsoft, `409` when a provider is already linked, `501` when the provider is not configured.

**Response 200:** `{ "authorize_url": "https://..." }`. The reply also sets the OAuth state cookie and a signed `oauth_link` cookie (10 minutes, httpOnly) that names this account and this session. The dashboard then sends the browser to `authorize_url`.

At the callback the link is made only when all of these hold: the state matches, the link cookie is valid and for this provider, the account and its session are still live and unchanged, the provider says the address is verified and that address equals the account's own address. Then the browser goes to `<dashboard>/profile?linked=<provider>`. A link never signs anybody in and sets no refresh cookie. A refusal never leaves the person on an API error page: the browser is redirected to `<dashboard>/profile?link_error=<code>` with one of these fixed codes and nothing else in the address (never an email, a provider identity, a token or a message): `address_mismatch` (the verified address is not the account's), `identity_in_use` (that provider account is linked to another account), `expired` (the link request or the session ended), `provider_unverified` (the provider does not say the address is verified), `cancelled` (the person declined at the provider) and `failed` for anything else. The link cookie and the state cookie are cleared in the same reply. The sign-in callback keeps its own behaviour and answers with the API's errors. Without the link cookie a callback behaves as an ordinary sign-in, which still refuses to link an address to an account that has a password.

---

### GET /auth/google

Initiate Google OAuth flow. Redirects to the Google consent screen with a random `state` value, which is also stored in a short-lived httpOnly cookie.

**Auth:** None (public)

---

### GET /auth/google/callback

Google OAuth callback. Refuses the request unless its `state` matches the cookie set by `GET /auth/google`. Exchanges the authorisation code and creates or finds the user by email, accepting only an email Google reports as verified.

No token is ever put in the redirect URL. Without 2FA it sets the refresh cookie and redirects to `/login?step=oauth`, where the dashboard exchanges the cookie for an access token. With 2FA it sets a sign-in challenge cookie and redirects to `/login?step=mfa` to ask for the code.

**Auth:** None (public)

---

### GET /auth/github

Initiate GitHub OAuth flow. Redirects to the GitHub consent screen with a random `state` value, which is also stored in a short-lived httpOnly cookie.

**Auth:** None (public)

---

### GET /auth/github/callback

GitHub OAuth callback. Refuses the request unless its `state` matches the cookie set by `GET /auth/github`. Exchanges the authorisation code and creates or finds the user by email, accepting only an email GitHub reports as verified.

No token is ever put in the redirect URL. Without 2FA it sets the refresh cookie and redirects to `/login?step=oauth`, where the dashboard exchanges the cookie for an access token. With 2FA it sets a sign-in challenge cookie and redirects to `/login?step=mfa` to ask for the code.

**Auth:** None (public)

---

### GET /auth/microsoft

Initiate Microsoft sign-in. Redirects to the Microsoft identity platform for the tenant in `MICROSOFT_TENANT` (`common` accepts personal and work or school accounts) with a random `state` value, which is also stored in a short-lived httpOnly cookie.

**Auth:** None (public)

---

### GET /auth/microsoft/callback

Microsoft sign-in callback. Refuses the request unless its `state` matches the cookie set by `GET /auth/microsoft`, then reads the profile from Microsoft Graph.

A work or school tenant can set any email on its users without verifying it, so a Microsoft email never links to an existing account. The callback signs in the account this Microsoft identity created before. With no such account it creates a new one when the email is unused. If the email already belongs to another account it returns 409 and the person signs in with their password or original provider instead. The redirect then works exactly as for Google and GitHub.

**Auth:** None (public)

---

### GET /auth/users

Return a paginated list of all users. Each row holds `id`, `name`, `email`, `role`, `created_at`, `oauth_provider`, `totp_enabled`, `is_active` (false for a deactivated account), `last_login` and `session_count` (live sessions now). It leaves out the phone number, which only the person's own `GET /auth/me` returns.

**Auth:** Bearer JWT (Admin only)

**Query params:** `skip` (at least 0), `limit` (default 50, 1 to 200)

---

### Retired: per-user permissions

`PATCH /auth/users/{user_id}/permissions` has been removed and no reply carries `permissions` any more. The field was stored and could be set but nothing ever read it, so it never changed what anyone could do. The database column stays so old rows still fit. Access follows the three roles and the machine rule only.

---

### POST /auth/invite

Send an invitation email to a new user. The email goes out through Resend from `FROM_EMAIL`. An invitation is a row in `invitations` holding only the hash of a 256-bit random token, the role, who sent it and when it expires, was used or was cancelled, so it can be listed and cancelled. A new invitation to an address cancels any earlier one still open for it. It expires after 48 hours. Invitations from before this change (signed links) no longer work and must be sent again.

**Auth:** Bearer JWT (Admin only). Inviting an `admin` also needs the inviter's fresh proof in the body (`password` and `code` when two-step is on).

**Request body:**

```json
{
  "email": "newuser@example.com",
  "role": "technician",
  "password": "only when role is admin"
}
```

**Response 201:**

```json
{
  "detail": "Invitation sent",
  "email_sent": true,
  "invite_link": "https://phaemos.com/accept-invite#token=..."
}
```

The link is built from `DASHBOARD_URL`. The token sits in the fragment (after `#`), which a browser never sends to a server, so it does not reach web server or hosting logs. The accept page reads it from `location.hash`. `email_sent` is `false` when Resend is not configured or the delivery failed. The `detail` then says the email could not be sent and the admin can share `invite_link` by hand. The link is returned either way because only an admin reaches this route.

---

### POST /auth/invite/check

Whether an invitation can still be used, without using it, so the dashboard can show a clear message before a person fills in the form. The token goes in the body and never in the address and the route is limited to 30/minute per address.

**Request body:** `{ "token": "<the invitation token>" }`

**Response 200:** `{ "status": "valid" }`, `{ "status": "expired" }` or `{ "status": "used" }`. Nothing about the account is returned. A token that is not a real invitation (made up, wrong, empty), one that was cancelled and one past its time all answer `expired`, because saying more would say what is wrong with it. An invitation that has been accepted or whose email now has an account, answers `used` and so does one whose account was deleted after it was accepted.

---

### GET /auth/invitations

The invitations that can still be used (not used, not cancelled, not expired), newest first. **Auth:** Bearer JWT (Admin only). **Response 200:** `[{ "id", "email", "role", "invited_by_name", "created_at", "expires_at" }]`. The token is never returned.

---

### DELETE /auth/invitations/{id}

Cancel a pending invitation. **Auth:** Bearer JWT (Admin only) with the admin's fresh proof. **Response 204.** An invitation that is not pending answers `404`. A cancelled invitation answers `expired` at `/auth/invite/check` and cannot be accepted. Audited.

---

### Admin control of accounts

Every route here needs an admin, the admin's fresh proof (see above) and writes an audit row naming the admin and the account (an id, never an address). All answer `204` unless said.

| Route | What it does |
| --- | --- |
| `POST /auth/users/{id}/deactivate` | The account cannot sign in, refresh, reset its password, accept an invitation or sign in through a provider. Every session ends at once. |
| `POST /auth/users/{id}/reactivate` | The account can sign in again. |
| `PATCH /auth/users/{id}/role` body `{ "role": "admin" \| "technician" \| "viewer" }` | Change the role. |
| `POST /auth/users/{id}/clear-two-step` | For a lost authenticator: two-step is switched off and every session ends, so the person signs in with their password and can enrol again. |
| `POST /auth/users/{id}/reset-link` | Email the account's **own address** a one-time link to choose a password. The link is never returned to the admin (`200 { "email_sent": true }`). `503` when the email could not be sent, `409` for a deactivated account, `429` for a second link inside 10 minutes. |
| `DELETE /auth/users/{id}` | Remove the account. Its tickets stay with the person taken off them, its sessions go with it and the audit trail is kept (it holds the account's id and no address). An account that still owns machines answers `409 Hand your machines to another person first`. |

Rules: an admin cannot deactivate, demote or remove their own account (`403`). The last active admin cannot be demoted, deactivated or removed (`409`). The admin rows are locked in a fixed order before the count, so two admins acting at once take turns and cannot each remove the other.

---

### POST /auth/reset-password

Choose a new password with a link an admin sent. **Auth:** none (the link is the credential). **Rate limit:** 10/minute per IP. **Body:** `{ "token": "<from the link, after #token=>", "password": "..." }`. **Response 204.** The link works once (it carries a marker of the old password), expires after 2 hours and ends every session of the account. Two-step stays on. Every refusal (bad, expired, used, deactivated) answers the same `400 This reset link is invalid or has expired`. The password rules include a list of common passwords that are refused.

---

### POST /auth/accept-invite

An invitation works once. A second use, even after the account it made was deleted, answers `400 This invitation has already been used`. A name over 100 characters answers `422`.

Set a password and activate an invited account.

**Auth:** None (public)

**Request body:**

```json
{
  "token": "signed-jwt-from-email",
  "password": "newpassword"
}
```

---

### POST /auth/2fa/enable

Generate a TOTP secret and a QR code for the current user. Does not activate 2FA until confirmed.

**Proof of ownership is needed**, so a stolen token cannot enrol someone else's authenticator and lock the owner out. Send `{"password": "..."}` for an account with a password. A provider account sends no body but must have returned from its provider within the last 5 minutes (see the deletion route for the exact messages). Without it: `400` `Enter your current password to turn on two-step sign-in` or `400` `Sign in with <Provider> again within the last 5 minutes to turn on two-step sign-in`.

**Auth:** Bearer JWT

**Response 200:**

```json
{
  "secret": "BASE32SECRET",
  "qr_code": "<base64 PNG>"
}
```

**Response 409:** 2FA is already enabled. Disable it first.

---

### POST /auth/2fa/confirm

Confirm TOTP enrolment by submitting the first valid code from the authenticator app. Activates 2FA on the account and ends every other session.

**Auth:** Bearer JWT

**Body:** `{"code": "123456"}`. The query parameter is no longer read, because a query string reaches proxy logs. A wrong code counts towards the sign-in lock.

**Response 200:** `{ "detail": "2FA enabled", "access_token": "eyJ...", "token_type": "bearer" }` plus a fresh refresh cookie for this browser.

---

### POST /auth/2fa/verify

The second step of sign-in for an account with 2FA. Needs the challenge from the first step: the `mfa_token` from `POST /auth/login` or the challenge cookie an OAuth callback set (leave `mfa_token` out then). A code on its own never signs anyone in.

**Auth:** None (uses the sign-in challenge)

**Rate limit:** 10/minute per IP

**Request body:**

```json
{
  "mfa_token": "eyJ...",
  "code": "123456"
}
```

**Response 200:** same as `/auth/login` - access token + refresh cookie

**Response 401:** the code is wrong, already used or the challenge has expired. Wrong codes are counted and slowed like wrong passwords.

**Response 429:** this source must wait (`Retry-After` says how long). The account is not locked.

Each code is accepted only once.

---

### POST /auth/2fa/disable

Disable 2FA on the current account. Requires a valid TOTP code and for an account with a password the password as well. Ends every other session.

**Auth:** Bearer JWT

**Body:** `{"code": "123456", "password": "..."}`. A provider account sends only the code. The query parameter is no longer read. A wrong code counts towards the sign-in lock. A missing password answers `400` `Enter your current password to turn off two-step sign-in`.

**Response 200:** `{ "detail": "2FA disabled", "access_token": "eyJ...", "token_type": "bearer" }` plus a fresh refresh cookie for this browser.

---

## API tokens

An API token lets a script, a service or the command line tool use the API without a person's password. It belongs to one account, is sent as `Authorization: Bearer pht_<id>_<secret>` and sets no cookie. The secret has 256 bits and is shown once, in the answer that creates the token. The server keeps the `<id>` in clear and a keyed hash of the secret, so the secret can never be read back. (The 15 minute token of a signed-in browser is the "access token". This is the "API token".)

The routes are at `/tokens`. The older `/auth/tokens` paths still work as deprecated aliases (see [API stability](api-stability.md)). Every error here has the `code` shape described in [API conventions](api-conventions.md).

### Scopes

| Scope | May do |
| --- | --- |
| `read` | every `GET` the account's role allows, except the administration reads below |
| `operate` | `read` plus the day-to-day writes the role allows: resolve an alert (the only alert action), work on a ticket, edit a machine's details (not its owner, tags or firmware version, which stay admin matters) and anything else a `POST`, `PUT`, `PATCH` or `DELETE` route open to the role allows without an admin check |
| `admin` | `operate` plus the admin routes that need no fresh proof (register or delete a machine, tags, alert rules, maintenance windows, webhook delete and test, model retrain and score) and the administration reads: `GET /audit-logs`, `GET /audit-logs/export` and `GET /webhooks`, which a `read` token cannot call |

The scope is decided by the method and the route and not by a list: a safe method (`GET`, `HEAD`, `OPTIONS`) needs `read`, any other method needs `operate` and a route that asks for an admin needs `admin` for every method, a `GET` included. No `GET` route changes anything and a test checks that. A token never has more than its account's role allows **at the moment of each request**: the role and the account's active state are read on every call, so lowering a role or deactivating the account takes effect on the next call. An `admin` token on an account that is no longer an admin counts as `operate`.

### What a token can never do

These answer `403` with code `session_required` and `{"detail": "A signed-in session is needed for this. An API token cannot do it"}`, whatever the scope: every route under `/auth` except `GET /auth/whoami` and `GET /auth/tokens`, the account administration routes (`/users`, `/invitations`, `/service-accounts`), making or revoking a token by id, every route that asks for a fresh proof (inviting an admin, adding or changing a webhook, firmware upload, rotating a machine's key, the admin controls over users) and the live socket (`/ws/telemetry/{id}`, which takes a session's access token only). A token with too low a scope for the method answers `403` with code `scope_too_low` and `This token's scope (read) does not allow this. It needs operate`. The one thing a token may do to tokens is revoke itself.

### POST /tokens

Session only and it asks for a fresh proof like the other dangerous actions.

Body:

```json
{ "name": "ci laptop", "scope": "read", "expires_in_days": 90, "password": "...", "code": "123456" }
```

`name` is 1 to 60 characters with no control characters (it is trimmed). `scope` is `read`, `operate` or `admin`. `expires_in_days` is 1 to 365 and defaults to 90. `password` is required and `code` is required when two-step is on (400 `proof_required` or `proof_wrong`, as for the other proofs). An admin may add `account_id`, the id of a **service account**, to make the token for it (see below).

| Status | Code | Meaning |
| --- | --- | --- |
| `201` | | `{"id": "a1b2c3d4e5f6", "name": "...", "scope": "read", "created_at": "...", "expires_at": "...", "account_id": "<uuid>", "token": "pht_<id>_<secret>"}`. The `token` is shown only here |
| `400` | `proof_required`, `proof_wrong`, `code_required` | the proof is missing or wrong |
| `403` | `session_required` | the caller is a token |
| `403` | `token_scope_forbidden` | `admin` was asked for an account that is not an admin |
| `403` | `admin_required` | `account_id` was sent by someone who is not an admin |
| `404` | `user_not_found` | `account_id` is not a service account (a person's account is never reachable this way) |
| `409` | `token_limit` | the account already has 20 live tokens |
| `422` | `validation_failed` | the body is not valid |
| `429` | `rate_limited` | more than 10 tokens an hour |

### GET /tokens

Session or token. Paged (`limit`, `offset`, `X-Total-Count`). `200` with a list of the account's tokens that are not revoked, newest first: `id`, `name`, `scope`, `created_at`, `expires_at`, `last_used_at` (`null` until first used, moved on at most once a minute), `account_id` and `created_by`. Never the secret. An expired token is listed until it is revoked. An admin may add `?account_id=<service account>` to list that account's tokens.

### DELETE /tokens/{id}

Session only. `204`. A token of another account, an unknown id and one already revoked answer `404 token_not_found`. An admin may revoke a service account's token.

### DELETE /tokens/current

Session or token, any scope. The API token that makes the call revokes itself. `204`. A session has no token to revoke (`400 no_token_in_use`). A token cannot revoke any other token.

### GET /auth/whoami

Session or token. `200`:

```json
{
  "id": "<account id>",
  "role": "technician",
  "signed_in_with": "token",
  "token": { "id": "a1b2c3d4e5f6", "name": "ci laptop", "scope": "read", "expires_at": "..." },
  "is_service": false
}
```

`signed_in_with` is `session` or `token`. For a session `token` is `null`. `role` is the role now. `scope` is the scope the token was made with.

### Bad tokens

An unknown, malformed, expired or revoked token answers `401` with code `token_invalid`, `{"detail": "Invalid or expired token"}` and `WWW-Authenticate: Bearer`. Each costs one keyed hash, so the answer and the time taken do not say which it was. A deactivated or removed account's tokens stop working at once. Anything that ends an account's sessions (changing the password, switching two-step on or off, signing out the other sessions, an admin clearing the sessions or deactivating the account, a password reset) revokes its tokens too.

### Limits

A limit on a route is counted per token for a token caller and per address otherwise, so two scripts behind one address do not starve each other. A made-up token gets no count of its own, because the key is set only after the token has been checked. Every call a token makes also counts against its account, 600 a minute across all its tokens, so making more tokens does not add up to a larger share (`429` with `Retry-After: 60`).

### Audit

Creating and revoking a token are logged (`token_created`, `token_revoked`, resource `api_token`). Every audit row a token's request writes ends with `[via token <id>]` in its `detail`, in the log, the CSV export and `GET /auth/me/export`. The export also lists the account's tokens (`access_tokens`: id, name, scope and dates, never a secret).

## Service accounts

A service account is an account owned by an integration and not by a person, so a script does not stop when the person who set it up leaves. It has a role and owns API tokens. It **cannot sign in by any route**.

### POST /service-accounts

Admin, session only, fresh proof (`password` and `code` in the body). Body `{"name": "ci bot", "role": "viewer", "password": "..."}` with `role` one of `admin`, `technician` or `viewer` (default `viewer`). `201` with the account (`id`, `name`, `email`, `role`, `is_service: true`...). The address is made up and never receives mail. Make its tokens with `POST /tokens` and `account_id`. Deactivate, reactivate, change the role or remove it with the `/users/{id}` routes. A service account shows in `GET /users` with `is_service: true`.

What closes each way in:

| Way in | Why it is closed |
| --- | --- |
| a password | it has none and the sign-in route answers for it exactly as for an unknown address (the same `invalid_credentials`, delay and counting), even if a hash is put there by hand |
| a provider | it has no provider link, `POST /auth/link/{provider}` needs a session and a provider sign-in that finds it is refused |
| an invitation | an invitation to its made-up address creates nothing: `account_exists` |
| a reset link | `POST /users/{id}/reset-link` answers `409 service_account_refused` and a link forged with the signing key is refused as invalid |
| two-step | enrolling needs a session |
| a session | no route starts one for it (the helper refuses) and an access token minted for it is refused as ended |

The audit rows name the admin who made the account and each token (`account=<id>`) and the token that acted on every later row.

## Firmware

### POST /firmware/upload

Upload the firmware image the machines fetch. **Auth:** Bearer JWT (Admin only) with fresh proof. At most 20 an hour.

**Query params:** `version` (required): dotted numbers such as `2.5.0`, up to four parts, else `422 validation_failed`. **Body:** multipart with a `file` that must be a `.bin` (`422 firmware_file_invalid` otherwise) of at most 2 MB (`413 firmware_too_large`).

**Response 201:** `{"version", "filename", "size", "checksum"}` (SHA-256 of the image).

---

### GET /firmware/latest

Returns the details of the latest uploaded firmware. The details are stored next to the firmware file, so they survive an API restart.

**Auth:** `X-API-Key` of a registered machine, checked the same way as telemetry ingest. A missing header answers `422` and an empty or unknown key answers `401`.

**Rate limit:** 30/minute per IP

**Response 200:**

```json
{
  "version": "v1.4.2",
  "filename": "firmware.bin",
  "size": 487320,
  "checksum": "sha256 hex digest"
}
```

`size` is in bytes and `checksum` is the SHA-256 of the file, so a device can verify its download. `404` when no firmware has been uploaded.

---

### GET /firmware/download

Download the latest firmware binary.

**Auth:** `X-API-Key` of a registered machine, with the same answers as `GET /firmware/latest`.

**Rate limit:** 10/minute per IP

**Response:** `application/octet-stream` binary. `404` when there is no file on the server.

---

## Health

### GET /health/summary

Health statistics for the machines the caller may read. Admins and viewers get fleet-wide totals. A technician's totals cover their own and unowned machines, their alerts and rules and tickets tied to those machines or to no machine.

**Auth:** Bearer JWT

**Response 200:**

```json
{
  "total_devices": 12,
  "online": 10,
  "offline": 2,
  "link_states": { "online": 9, "late": 1, "offline": 2 },
  "active_alerts": 3,
  "open_tickets": 5,
  "health_score": 84
}
```

`link_states` counts the same machines by link state. `online` and `offline` are counted from `status` as before.

---

## Status (public)

### GET /status

The page for uptime monitors and the status page. No authentication. 120 a minute per address. It always answers **200**, because a monitor reads the body and it shows nothing else about the deployment (never the environment).

**Response 200:**

```json
{
  "status": "operational",
  "api": "ok",
  "database": "ok",
  "redis": "ok",
  "model": "ok",
  "version": "2.5.0",
  "updated_at": "2026-06-03T10:00:00Z"
}
```

Every value each field can take:

| Field | Values |
| --- | --- |
| `status` | `operational` when the database and Redis both answer, `degraded` when either does not |
| `api` | `ok` (the process answered) |
| `database`, `redis` | `ok` or `error` |
| `model` | `none` (no model file yet), `ok`, `legacy` (a file from before missing values stopped being filled with zero) or `error` (the file will not load, so readings are stored without a score). `deploy.sh` fails on `error` |
| `version` | the release the API belongs to, the same as `version` at `GET /` |
| `updated_at` | the server's clock in UTC, ending in `Z`. A client may compare its own clock against it (a skew of more than a few minutes breaks signed requests and makes times look wrong) |

### GET /

Liveness for a container health check: `{"status": "ok", "service": "PHAEMOS API", "version": "2.5.0", "api_version": "v1"}`. `version` is the release (the `RELEASE_VERSION` the deploy sets) and `api_version` is the path prefix. Neither names the environment.

### GET /livez and GET /readyz

`/livez` answers `{"status": "ok"}` while the process is up and checks nothing else. `/readyz` answers the same when the database and Redis answer and **503** (`unavailable`, naming which one) when either does not. Use `/readyz` to decide whether to send traffic and `/livez` to decide whether to restart.

### GET /fleet/summary

The fleet statistics for the signed-in caller (`total_devices`, `online`, `offline`, `link_states`, `active_alerts`, `open_tickets`, `health_score`), counted over what the caller may read. It was `GET /health/summary`, which still works as a deprecated alias until 20 February 2027.

---

## Maintenance Windows

### GET /maintenance-windows

List maintenance windows, newest start first (ending in id), with `X-Total-Count`. A technician receives windows for machines they may read plus fleet-wide windows (no machine). **Query params:** `device_id`, `active` (inside the window now), `from` (windows that end at or after it), `to` (windows that start at or before it), `limit` (default 50, at most 200) and `offset`.

**Auth:** Bearer JWT

### GET /maintenance-windows/{window_id}

One window. A window on a machine the caller may not read answers `404 window_not_found`.

---

### POST /maintenance-windows

Create a maintenance window. Optionally scoped to a specific device.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "label": "Monthly pump inspection",
  "start_at": "2026-06-10T08:00:00Z",
  "end_at": "2026-06-10T12:00:00Z",
  "suppress_alerts": true,
  "device_id": "uuid or null"
}
```

---

### PATCH /maintenance-windows/{window_id}

Update a maintenance window's label, times or suppress_alerts flag. A field left out is kept. `device_id` may be set to `null`, which makes the window fleet-wide. Any other `null` answers `422`. An end before the start answers `422 invalid_range` and an unknown machine `404 device_not_found` (as on create).

**Auth:** Bearer JWT (Admin only)

---

### DELETE /maintenance-windows/{window_id}

Delete a maintenance window.

**Auth:** Bearer JWT (Admin only)

---

## Webhooks

### GET /webhooks

List webhooks, newest first (ending in id), with `X-Total-Count`. `enabled` filters; `limit` (default 50, at most 200) and `offset` page. Each webhook carries its delivery state: `last_delivery_at`, `last_status` (the HTTP status the receiver answered, null when nothing answered), `last_error` (a short reason when it failed) and `consecutive_failures` (deliveries in a row that failed after their tries). `has_secret` says whether a signing secret exists. No route ever returns the secret again.

**Auth:** Bearer JWT (Admin only)

### GET /webhooks/{webhook_id}

One webhook, with the same fields.

---

### POST /webhooks

Create a webhook. Two formats. `chat` (the default) sends a message for Slack, Discord or Teams, chosen from the address. `json` sends the signed event body described below, for a program to read.

**Address rules:** the address must be `https` (`http` is accepted only in development) and every address its host resolves to must be public. An address that is a private, loopback, link-local or shared address or holds a user name or password, answers `422 webhook_url_refused`. Delivery connects to the checked address, checks it again at every attempt and never follows a redirect.

**Template (chat only).** A message with the placeholders `{device_name}`, `{metric}`, `{value}`, `{threshold}` and `{severity}`. Nothing else is allowed, no attribute, index, conversion or format. It is checked when it is saved: `422 webhook_template_invalid` says what is wrong. A `json` webhook takes no template. A chat message to Discord also sets `allowed_mentions` to none.

**Auth:** Bearer JWT (Admin only) with fresh proof. Accepts `Idempotency-Key`.

```json
{
  "name": "Ops pipeline",
  "url": "https://hooks.example.org/phaemos",
  "enabled": true,
  "format": "json",
  "template": null
}
```

**Response 201:** the webhook and for a `json` webhook the `secret` (`whsec_...`), **shown once**. Store it now: it is encrypted at rest under a key derived from the server's secret key for this purpose (and still opens after the server key is rotated, because the previous key is tried) and no route returns it again. `POST /webhooks/{id}/rotate-secret` makes a new one (shown once). A chat webhook changed to `json` gets its secret in the answer to that `PATCH`.

#### The json event

```json
{
  "id": "evt_5f0c...",
  "type": "alert.raised",
  "version": 1,
  "created_at": "2026-11-22T11:40:12Z",
  "data": {
    "reason": "raised",
    "alert": {"id": "uuid", "kind": "rule", "severity": "critical", "metric": "temperature", "condition": "gt",
              "value": 81.2, "threshold": 80.0, "peak_value": 83.0, "occurrences": 7, "message": "...",
              "resolved": false, "triggered_at": "2026-11-22T11:40:12Z", "first_seen_at": "2026-11-22T11:39:42Z"},
    "device": {"id": "uuid", "name": "Pump 1"}
  }
}
```

`type` is `alert.raised` (with `data.reason` `raised`, `escalated` for a rise to critical or `reminder` for the hourly reminder), `alert.resolved` (only json webhooks are told) or `webhook.test` (`data.message` only). `id` names this delivery. Delivery is at least once: a later reminder carries a new `id` and the same `data.alert.id`, so dedupe an alert by that.

#### Verifying the signature

Every json delivery carries `X-Phaemos-Signature: t=<unix seconds>,v1=<hex>`, where `v1` is the HMAC-SHA256, under the webhook's secret, of the text `<t>.<raw body>`. Compute it over the **raw bytes** you received (not a re-serialised copy), compare in constant time and refuse a `t` more than five minutes from your own clock. Each attempt is signed with its own `t`. `X-Phaemos-Event` and `X-Phaemos-Delivery` repeat the type and the delivery id.

```python
import hashlib, hmac, time

def verify(secret: str, raw_body: bytes, header: str, tolerance_s: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    stamp, signature = int(parts["t"]), parts["v1"]
    if abs(time.time() - stamp) > tolerance_s:
        return False                                   # too old or from the future: a replay
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

#### Delivery

Up to three tries with a pause of 2 and then 8 seconds, run by the notification pool (a delivery ends within about 25 seconds). A `4xx` other than 408 and 429 is the receiver saying no and is not tried again. The outcome is kept on the webhook. The hourly repeat window and the daily caps are unchanged.

---

### PATCH /webhooks/{webhook_id}

Update a webhook. A field left out is kept. `template` may be set to `null` (the built-in message). Any other `null` answers `422`. Switching a webhook on checks its address again, clears `disabled_reason` and resets `consecutive_failures`. Changing `format` to `json` makes the secret and returns it once.

**Auth:** Bearer JWT (Admin only) with fresh proof.

### POST /webhooks/{webhook_id}/rotate-secret

A new signing secret for a `json` webhook, returned once. The old one stops signing at once, so update the receiver first. `422 webhook_not_json` for a chat webhook. **Auth:** Bearer JWT (Admin only) with fresh proof.

---

### DELETE /webhooks/{webhook_id}

Delete a webhook.

**Auth:** Bearer JWT (Admin only)

---

### POST /webhooks/{webhook_id}/test

Send one test delivery (no retries) and say what happened. A `json` webhook gets a signed `webhook.test` event. The outcome is kept on the webhook. At most 10 a minute.

**Auth:** Bearer JWT (Admin only)

**Response 200** when the receiver accepted it:

```json
{ "ok": true, "status": 204, "elapsed_ms": 138 }
```

A failure is not a 200: `502 webhook_delivery_failed` with `detail` such as "The test delivery failed (HTTP 500) after 312 ms" and `errors: [{"status": 500, "elapsed_ms": 312}]` (`status` is null when nothing answered). An address that is not safe answers `422 webhook_url_refused`.

---

## Audit

### GET /audit-logs

Returns paginated audit log entries.

**Auth:** Bearer JWT (Admin only)

**Query params:** `skip` (at least 0), `limit` (default 50, 1 to 500)

---

### GET /audit-logs/export

Export filtered audit log entries as a CSV file. Response includes an `X-Signature` header containing an HMAC-SHA256 of the CSV body for integrity verification.

**Auth:** Bearer JWT (Admin only)

**Query params:** `from` (ISO datetime), `to` (ISO datetime), `action` (string filter), `user_id` (UUID filter)

**Response:** `text/csv` with `Content-Disposition: attachment` and `X-Signature: sha256=<hmac>`

---

## Contact

### POST /contact

Submit a contact form message. Turnstile token is verified server-side before the email is sent. The message goes through Resend from `FROM_EMAIL` to `CONTACT_EMAIL_TO`, with the visitor's address as Reply-To.

**Auth:** None (public)

**Rate limit:** 3/hour per IP. The count includes refused attempts, such as a failed check or a 503.

**Request body:**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "subject": "A question",
  "message": "Hello, I have a question about...",
  "turnstile_token": "..."
}
```

`name`, `subject` and `message` must not be empty after trimming spaces. `name` is at most 100 characters, `subject` at most 200 and `message` at most 5000. Anything outside that is a 422. The email subject is `[Contact]`, a space and the visitor's subject, cut so the whole fits in 200. Control characters are removed before sending.

**Response 204:** the message was accepted. No body.

**Response 422:** the Turnstile check failed or no token was sent while a secret is configured.

**Response 503:** the check could not run. Either Cloudflare could not be reached (the call has a 5 second timeout) or `TURNSTILE_SECRET_KEY` is empty while `ENVIRONMENT` is anything but `development`. In development an empty secret skips the check. Two more cases are a 503. Resend refuses the message or times out (5 second timeout). Or `RESEND_API_KEY` is empty or `placeholder` while `ENVIRONMENT` is anything but `development`. The detail asks the visitor to email us directly. In development with no Resend key the message is logged and the answer is 204.

---

## ML

### POST /ml/retrain

Trigger a background retrain of the anomaly models. Returns immediately with 202 and the task runs asynchronously. It reads the last 14 days of each machine, one machine at a time. It keeps only clean readings: none taken in a maintenance window, with a sensor fault or a rejected or dropped value, beside a gap in the posts or while a rule alert or a model alert a person confirmed as a real fault (`POST /ml/alerts/{alert_id}/verdict`) was open. The model's own unconfirmed alert refuses nothing, so a machine whose normal really changed is retrained on it. A machine's clean readings are split by time into a fit part, a validation part (every limit is set on it) and a test part (only the reported figures come from it). The sampling and the caps are in the architecture page. The result, accepted or refused, is at `GET /ml/status` and in the audit log.

**Auth:** Bearer JWT (Admin only)

**Response 202:**

```json
{ "detail": "Retrain started. The result is at GET /api/v1/ml/status when it finishes." }
```

**Response 429 (cooldown active):**

```json
{ "code": "retrain_cooldown", "detail": "Retrain cooldown active. Try again in 47 minutes.", "request_id": "..." }
```

A retrain does not replace a model in service with a worse one. A new model is refused when it would raise more than one false anomaly alert per machine per week on the validation readings, when it finds fewer than 60 per cent of the faults injected into them (or none could be injected), when its change detector's boundary could hardly ever be crossed, when on the same newest readings it raises more false alerts than both the model in service and the budget or catches a tenth fewer of the same faults. It is also refused when it would move the machine's normal more than one in-state spread from the model in service or two from the first model accepted for it. The last needs a person: `POST /ml/machines/{device_id}/accept-move`. The model in service is left untouched and is carried over for at most 7 days after it was trained, after which it is withdrawn and the machine is shown as not monitored. When no model is accepted nothing is saved.

A machine the retrain leaves with no working model gets one open monitoring alert (`kind` `unmonitored`, "Not monitored by the anomaly model: ..." with the reason) and a machine whose new model needs a person gets one (`kind` `model_move`, "Anomaly model needs a person: ..."). Both resolve at the first retrain that gives the machine a working model.

The audit log entry is `retrain` when a bundle was saved, `retrain_refused` when none was and `retrain_error` when the task failed. Refusals read like these:

- `<machine> would still have raised 3.2 false alerts per machine per week on healthy readings it did not train on, after tightening its limit 3 times. The budget is 1. The model in service is untouched. Let the machine run a few more normal days and retrain. Also look for a sensor that wanders.`
- `<machine> caught 6 of 20 faults injected into healthy readings and at least 60 per cent are needed. A model that finds too few faults is not worth having. The model in service is untouched. Retrain once more of the machine's range of normal behaviour has been recorded.`
- `The new model raised 3 false alerts on the newest 42 hours of healthy readings where the model in service raised 0, so the model in service is kept.`
- `The new model would move this machine's normal temperature by 2.4 of its usual spreads from the first model accepted for it (the bound is 2.0). A slow walk like that is what a drifting fault or a forged sensor looks like, so the model in service is kept and a person must accept the move: POST /api/v1/ml/machines/<id>/accept-move, then retrain.`
- `<machine>'s change detector measured a boundary of 1700, above 50% of its cap of 3000, so it could hardly ever raise an alert. ...`
- `<machine> has 412 training readings, 1500 held back for setting its limits and 9.0 hours held back for testing. It needs at least 500, 2000 and 24 hours. It stays in learning and is not scored by a model of its own until it has them, so leave it running.`

---

### GET /ml/status

What is in service and the outcome of the latest retrain. `schedule` holds `nightly_utc` (the time the nightly retrain runs) and `next_at`. `last_retrain.trigger` is `manual` or `nightly`.

**Auth:** Bearer JWT (any role)

**Response:**

```json
{
  "state": "ok",
  "trained_at": "2026-03-02T04:10:00+00:00",
  "models": [
    { "key": "machine:6f1c0e5a-0000-0000-0000-000000000001", "scope": "machine", "legacy": false, "light": false,
      "false_alerts_per_week": 0.0, "false_alerts_per_week_high_95": 14.87,
      "features": ["temperature", "vibration_x", "current_ma"], "trained_at": "2026-03-02T04:09:41+00:00",
      "detector": { "boundary": 24.1, "crossings": 0, "hours_watched": 41.7, "censored": true, "arl_hours": null,
                    "arl_hours_lower_95": 13.9 } }
  ],
  "max_machine_models": 24,
  "monitored_machines": 1,
  "unmonitored_machines": 1,
  "machines": [
    { "device_id": "6f1c0e5a-0000-0000-0000-000000000001", "state": "ready", "scope": "machine", "over_cap": false,
      "light": false, "monitored": true, "hours_collected": 318.2, "hours_needed": 120.0, "reason": null,
      "ambient": "no ambient reference: ...", "interval_s": 5.0, "recorded_interval_s": null },
    { "device_id": "6f1c0e5a-0000-0000-0000-000000000099", "state": "none", "scope": null, "over_cap": false,
      "light": false, "monitored": false, "hours_collected": 200.0, "hours_needed": 120.0,
      "reason": "<machine> caught 6 of 20 faults injected into healthy readings and at least 60 per cent are needed. ...",
      "ambient": null, "interval_s": 30.0, "recorded_interval_s": 5.0 }
  ],
  "last_retrain": {
    "status": "trained",
    "finished_at": "2026-03-02T04:10:07+00:00",
    "summary": "Retrain: 3 models accepted (worst false alert rate on the newest held-back readings 0.00 per machine per week); 1 refused: ... 1 of 2 machines have no working model and are not monitored by the model.",
    "unmonitored": { "6f1c0e5a-0000-0000-0000-000000000099": "..." },
    "moves": {},
    "models": [ { "key": "machine:6f1c0e5a-0000-0000-0000-000000000001", "state": "ready", "validation": { "alerts": 0, "hours": 41.67, "per_week": 0.0 }, "test": { "alerts": 0, "hours": 41.67, "per_week": 0.0, "per_week_low_95": 0.0, "per_week_high_95": 14.87 } } ],
    "learning": []
  }
}
```

`state` is `none` (no model file), `ok`, `legacy` (a signed file from an earlier version, which scores nothing until a retrain) or `error` (the file will not load or is not signed by this server). `false_alerts_per_week` is the figure on the test part (the newest held-back readings, which nothing was tuned on) and `false_alerts_per_week_high_95` its exact 95 per cent upper bound: a figure from two or three days of one machine cannot promise more. The detector's run length between false crossings is censored when no crossing was seen: `arl_hours` is then null and only `arl_hours_lower_95` is known. `machines` has one line per machine the last training saw. `monitored` is false for a machine no model scores and `reason` says why (learning, refused, withdrawn or no pooled model to fall back on). A machine beyond the cap on full models (`ML_MAX_MACHINE_MODELS`, default 24, oldest machines first) has a light model of its own (`light` true: the baseline and the change detector without the forest). `interval_s` is the posting interval the readings show and `recorded_interval_s` the device record's when the two differ by more than half again. `ambient` says how the machine's own model uses the room. The same figures for one machine are in the `model` object of the device read.

---

### POST /ml/machines/{device_id}/accept-move

Allow the next retrain to move this machine's normal past the bound and re-anchor it there. Use it when a retrain was refused because the new model would move the machine's normal too far and a person knows the change is real (a new product, a season, a repair). Then retrain. The acceptance is used once. The bound is the guard against a slow forged walk of a machine's readings, so lifting it is a signed-in admin's decision with fresh proof and never something an API token can do.

**Auth:** Bearer JWT of a signed-in session (Admin only). An API token answers 403 `session_required`.

**Request body:** the fresh proof, as for the other dangerous admin actions: `{"password": "...", "code": "123456"}` (the code when two-step sign-in is on). A missing or wrong proof answers 400.

**Rate limit:** the `sensitive` class.

**Response:**

```json
{ "detail": "Accepted. The next retrain may move this machine's normal and re-anchor it. Retrain to apply it." }
```

The audit log entry is `model_move_accepted` on the device, with the admin who decided.

---

### PUT /ml/machines/{device_id}/ambient-source

Set the node whose air temperature is this machine's ambient reference (or clear it with `null`). Use it for a machine whose node has no air temperature of its own beside a machine temperature: the next retrain models the machine's temperatures as their rise above that node's reading, so a warmer room is not read as a warmer machine. The source should stand in the same place.

**Auth:** Bearer JWT or an API token with the `admin` scope (Admin only).

**Request body:** `{"source_id": "<device id>"}` or `{"source_id": null}`. The source must be another machine the caller may read: a machine cannot be its own source (422).

**Rate limit:** the `write` class.

**Response:**

```json
{ "device_id": "...", "source_id": "...", "detail": "Set. The next retrain uses it as this machine's ambient reference." }
```

The audit log entry is `ambient_source_set` on the device. A machine's `ambient` field in its status says which reference it uses: its own air temperature, the site's reference or none.

---

### POST /ml/alerts/{alert_id}/verdict

Record a person's verdict on a machine alert. Only a model alert confirmed as a real fault keeps its readings out of the model's training.

**Auth:** Bearer JWT or an API token with the `operate` scope. The people who may resolve the alert may give it: an admin or a technician on a machine they may change. A viewer answers 403.

**Request body:** `{"fault": true}` (a real fault) or `{"fault": false}` (not one)

**Rate limit:** the `write` class.

**Response:**

```json
{ "id": "1b9c4c1e-0000-0000-0000-000000000003", "fault_confirmed": true }
```

An alert that does not exist, is not a machine alert or is on a machine the caller may not read answers 404 `alert_not_found`. The audit log entry is `alert_verdict` on the alert, with the verdict, the value before it and who gave it.

---

### POST /ml/score

Score a single reading manually (useful for testing the model). When `device_id` names a machine that exists the machine access rule is applied and its own model is used.

**Auth:** Bearer JWT (Admin only: any other role answers 403)

**Request body:** same as telemetry payload

**Response:**

```json
{
  "anomaly_score": 0.83,
  "is_anomaly": true
}
```

---

### GET /ml/anomalies/{device_id}

Returns the most recent anomalous telemetry rows for a device.

**Query params:** `limit` (default 100, 1 to 1000) and `offset` (default 0). A value outside the range answers `422`. The answer carries `X-Total-Count`, the number of anomalous rows before paging.

**Auth:** Bearer JWT, with the same machine rule as `GET /telemetry/{device_id}`

---

## WebSocket

### WS /ws/telemetry/{device_id}

Receive live telemetry pushes for a single device without polling.

**Auth:** the access token in the first message. Connect to `/ws/telemetry/{device_id}` with no query string, then send one text frame within 5 seconds:

```json
{ "type": "auth", "token": "<access token>" }
```

The frame may hold at most 4096 characters. A timeout, a frame that is not text, one that is too long, bad JSON and any other shape are refused with `1008`, like a bad token. The server subscribes the client only after the token is accepted.

The older form, `?token=<jwt>` in the URL, works while `WS_TOKEN_IN_URL` allows it and logs one warning per process. The setting is on by default in development and **off by default everywhere else**, where a socket opened with `?token=` is accepted and closed with `1008` without its token being read. It puts the token in the URL, which proxies and logs can record, so new clients must use the first message. The same machine rule applies: a technician cannot subscribe to another technician's machine.

The server accepts the connection first and then closes a refused one at once with `1008`, without subscribing it and without sending anything, so a browser sees the close code. A bad token, a missing machine and a machine the caller may not read are closed in the same way. An open socket is closed with `1008` when its token expires. Every 60 seconds it also re-checks that the session is still valid, the role and that the caller may still read the machine. It closes with `1008` when the answer has changed. Request a new access token and reconnect after a close.

**Limits:** one account may hold 5 live sockets and one address 20 (`WS_MAX_PER_USER`, `WS_MAX_PER_ADDRESS`). A socket over either limit is accepted and closed with `1008`, like any other refusal. A client may send nothing larger than 4096 characters at any time: a bigger message ends the socket with `1008`. The server is also started with a message size cap of 8192 bytes and with compression off, so a larger message is refused before it is read into memory.

**Close codes:**

- `1008` - refusal or end of access. This covers an invalid or missing token, a machine the user may not read, one that does not exist, an expired token and a session, role or machine rule that changed while connected. The frontend must not retry on 1008 to avoid an infinite loop on an expired token.

**Messages:** Server pushes the same JSON shape as `TelemetryResponse` whenever a new reading is ingested via `POST /telemetry`.

---

## Demo

### POST /demo/start

Register (or reuse) a Demo Node virtual device and start a 5-second APScheduler job generating synthetic telemetry. A key is stored only as a hash, so `api_key` is returned when the machine is made and is `null` when an existing one is reused.

**Auth:** Bearer JWT (Admin only). Only in development: the demo feed is switched off elsewhere.

**Response:**

```json
{ "device_id": "uuid", "api_key": "string or null", "status": "started" }
```

---

### POST /demo/stop

Cancel the demo telemetry job.

**Auth:** None

---

## Error Responses

Every error has one shape, `{"code": "...", "detail": "...", "request_id": "..."}` (`errors` is added for validation). Read `code`, never `detail`. The full list of codes and the rules are in [API conventions](api-conventions.md). A 429 always carries `Retry-After`.

| Status | Meaning |
| ------ | ------- |
| 400 | A proof (password or two-step code) is missing or wrong |
| 401 | Missing, bad, expired or revoked credential |
| 403 | Insufficient role, scope or session. Also a caller who can read an item but not change it |
| 404 | Resource not found. Also a machine or item the caller may not read |
| 409 | Conflicts with the current state: a duplicate, the last admin, a stale replay |
| 413 | Too large |
| 422 | The request is not valid. `errors` says where |
| 429 | Limited. Wait `Retry-After` seconds |
| 500 | Something went wrong on our side. Quote `request_id` |
| 503 | A dependency is down or the work timed out |
