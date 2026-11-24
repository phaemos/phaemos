//! gives every reading the gateway's own `(boot, seq)` pair before it is spooled.
//!
//! the API judges each post against the last pair it accepted for the key. The gateway is the one
//! posting under its key, so the pair is the gateway's and not the node's: readings from several nodes
//! share one stream and the nodes' own counters would clash. The pair is written into the reading as it
//! enters the spool, so a resend after a crash carries the same pair and is answered as a duplicate and
//! never refused as older.
//!
//! `boot` is a counter kept in a small file in the state folder. At each start it becomes the larger of
//! the stored value plus one and the Unix time in seconds (capped at the API's limit), so it still
//! rises when the file was wiped. `seq` starts at 0 each boot and rises by one per reading. A reading
//! that already carries a `boot` or `seq` from its node keeps them as `node_boot` and `node_seq` (the
//! API ignores unknown fields) so nothing is lost.

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::fsutil;

/// the largest `boot` the API accepts.
pub const MAX_BOOT: u64 = 2_147_483_647;
/// the largest `seq` the API accepts.
pub const MAX_SEQ: u64 = 4_294_967_295;

pub struct Stamper {
    path: PathBuf,
    boot: u64,
    seq: u64,
}

/// the time as UTC ISO 8601 with a Z, from Unix seconds.
#[must_use]
pub fn rfc3339_utc(secs: u64) -> String {
    let days = i64::try_from(secs / 86_400).unwrap_or(0);
    let rest = secs % 86_400;
    // civil date from days since 1970-01-01 (Howard Hinnant's algorithm)
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

fn store(path: &Path, boot: u64) -> io::Result<()> {
    let mut temp = path.as_os_str().to_os_string();
    temp.push(".tmp");
    let temp = PathBuf::from(temp);
    {
        let mut file = fsutil::create_private_new(&temp)?;
        writeln!(file, "{boot}")?;
        file.sync_data()?;
    }
    fs::rename(&temp, path)
}

impl Stamper {
    /// starts a new boot: reads the stored counter, picks the next value and stores it.
    ///
    /// # Errors
    ///
    /// returns an error when the counter cannot be stored (the gateway then does not start, because
    /// a pair that could repeat would be refused) or has reached the API's limit.
    pub fn open(path: impl AsRef<Path>, now_secs: u64) -> io::Result<Self> {
        let path = path.as_ref().to_path_buf();
        let previous = fs::read_to_string(&path)
            .ok()
            .and_then(|text| text.trim().parse::<u64>().ok())
            .unwrap_or(0);
        let from_clock = now_secs.min(MAX_BOOT);
        let boot = previous.saturating_add(1).max(from_clock);
        if boot > MAX_BOOT {
            return Err(io::Error::other(
                "the boot counter has reached the API's limit",
            ));
        }
        store(&path, boot)?;
        Ok(Self { path, boot, seq: 0 })
    }

    #[must_use]
    pub fn boot(&self) -> u64 {
        self.boot
    }

    /// returns the reading with this gateway's pair added.
    ///
    /// # Errors
    ///
    /// returns a message when the line is not a JSON object or the boot counter cannot move on.
    pub fn stamp(&mut self, line: &str, now_secs: u64) -> Result<String, String> {
        if self.seq > MAX_SEQ {
            // the sequence is used up: a new boot starts it again
            let boot = self.boot + 1;
            if boot > MAX_BOOT {
                return Err("the boot counter has reached the API's limit".to_string());
            }
            store(&self.path, boot).map_err(|e| format!("cannot store the boot counter: {e}"))?;
            self.boot = boot;
            self.seq = 0;
        }
        let mut value: Value = serde_json::from_str(line).map_err(|e| format!("not JSON: {e}"))?;
        let object = value
            .as_object_mut()
            .ok_or("reading must be a JSON object")?;
        if let Some(old) = object.remove("boot") {
            object.insert("node_boot".to_string(), old);
        }
        if let Some(old) = object.remove("seq") {
            object.insert("node_seq".to_string(), old);
        }
        // when the gateway took the reading in. A reading that comes out of a backlog is then dated by when it
        // was seen and not by when it was sent. A time the node already put there is kept: it knows better
        object
            .entry("observed_at".to_string())
            .or_insert_with(|| Value::from(rfc3339_utc(now_secs)));
        object.insert("boot".to_string(), Value::from(self.boot));
        object.insert("seq".to_string(), Value::from(self.seq));
        self.seq += 1;
        serde_json::to_string(&value).map_err(|e| e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::{Stamper, MAX_BOOT};
    use serde_json::Value;
    use std::path::PathBuf;

    fn temp(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-stamp-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("boot")
    }

    fn pair(line: &str) -> (u64, u64) {
        let v: Value = serde_json::from_str(line).unwrap();
        (v["boot"].as_u64().unwrap(), v["seq"].as_u64().unwrap())
    }

    #[test]
    fn pairs_rise_within_a_boot() {
        let mut s = Stamper::open(temp("rise"), 1_800_000_000).unwrap();
        let a = pair(&s.stamp(r#"{"device_id":"x"}"#, 1_800_000_000).unwrap());
        let b = pair(&s.stamp(r#"{"device_id":"x"}"#, 1_800_000_000).unwrap());
        assert_eq!(a, (1_800_000_000, 0));
        assert_eq!(b, (1_800_000_000, 1));
    }

    #[test]
    fn every_start_is_a_newer_boot_even_with_the_clock_unchanged_or_set_back() {
        let path = temp("boots");
        let first = Stamper::open(&path, 1_800_000_000).unwrap().boot();
        let second = Stamper::open(&path, 1_800_000_000).unwrap().boot();
        let third = Stamper::open(&path, 1_700_000_000).unwrap().boot();
        assert!(first < second && second < third);
    }

    #[test]
    fn a_wiped_state_folder_still_starts_above_an_earlier_clock_boot() {
        let path = temp("wipe");
        let before = Stamper::open(&path, 1_800_000_000).unwrap().boot();
        std::fs::remove_file(&path).unwrap();
        let after = Stamper::open(&path, 1_800_000_100).unwrap().boot();
        assert!(after > before);
    }

    #[test]
    fn boot_never_exceeds_the_apis_limit() {
        let s = Stamper::open(temp("cap"), 9_999_999_999).unwrap();
        assert_eq!(s.boot(), MAX_BOOT);
        // and a counter already at the limit cannot go further
        let path = temp("cap2");
        std::fs::write(&path, MAX_BOOT.to_string()).unwrap();
        assert!(Stamper::open(&path, 1).is_err());
    }

    #[test]
    fn the_pair_is_in_the_line_so_a_resend_is_the_same_post() {
        let mut s = Stamper::open(temp("same"), 1_800_000_000).unwrap();
        let line = s
            .stamp(r#"{"device_id":"x","temperature":1.5}"#, 1_800_000_000)
            .unwrap();
        // the spool keeps this exact text: sending it again repeats the pair
        assert_eq!(pair(&line), pair(&line));
        assert!(line.contains("\"temperature\":1.5"));
    }

    #[test]
    fn a_pair_from_the_node_is_kept_under_other_names_and_replaced() {
        let mut s = Stamper::open(temp("node"), 1_800_000_000).unwrap();
        let line = s
            .stamp(r#"{"device_id":"x","boot":3,"seq":99}"#, 1_800_000_000)
            .unwrap();
        let v: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(v["node_boot"], 3);
        assert_eq!(v["node_seq"], 99);
        assert_eq!(v["boot"], 1_800_000_000u64);
        assert_eq!(v["seq"], 0);
    }

    #[test]
    fn bad_lines_are_refused() {
        let mut s = Stamper::open(temp("bad"), 1_800_000_000).unwrap();
        assert!(s.stamp("not json", 1).is_err());
        assert!(s.stamp("[1]", 1).is_err());
    }

    #[test]
    fn the_sequence_used_up_starts_a_new_boot() {
        let mut s = Stamper::open(temp("seq"), 1_800_000_000).unwrap();
        s.seq = super::MAX_SEQ;
        let last = pair(&s.stamp(r#"{"device_id":"x"}"#, 1_800_000_000).unwrap());
        let next = pair(&s.stamp(r#"{"device_id":"x"}"#, 1_800_000_000).unwrap());
        assert_eq!(last, (1_800_000_000, 4_294_967_295));
        assert_eq!(next, (1_800_000_001, 0));
    }

    #[cfg(unix)]
    #[test]
    fn the_counter_file_is_private() {
        use std::os::unix::fs::PermissionsExt;
        let path = temp("mode");
        Stamper::open(&path, 1_800_000_000).unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }

    #[test]
    fn observed_at_is_stamped_in_utc_and_a_nodes_own_is_kept() {
        let mut s = Stamper::open(temp("observed"), 1_800_000_000).unwrap();
        let line = s.stamp(r#"{"device_id":"x"}"#, 1_795_345_245).unwrap();
        let v: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(v["observed_at"], "2026-11-22T11:00:45Z");
        let kept = s
            .stamp(
                r#"{"device_id":"x","observed_at":"2026-11-22T10:00:00Z"}"#,
                1_795_345_245,
            )
            .unwrap();
        let v: Value = serde_json::from_str(&kept).unwrap();
        assert_eq!(v["observed_at"], "2026-11-22T10:00:00Z");
    }

    #[test]
    fn rfc3339_is_right_on_known_dates() {
        use super::rfc3339_utc;
        assert_eq!(rfc3339_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(rfc3339_utc(951_782_400), "2000-02-29T00:00:00Z"); // a leap day
        assert_eq!(rfc3339_utc(1_709_209_199), "2024-02-29T12:19:59Z");
        assert_eq!(rfc3339_utc(4_102_444_800), "2100-01-01T00:00:00Z");
        assert_eq!(rfc3339_utc(1_795_345_245), "2026-11-22T11:00:45Z");
    }
}
