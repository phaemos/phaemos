//! a disk-backed queue of readings waiting to be forwarded.
//!
//! each reading is one record in an append-only file, synced to disk before it is acknowledged, so a
//! power cut or network outage never loses telemetry. A record is `<unix seconds>\t<json>\n` and the
//! file starts with a header line `#phaemos-spool <generation>`.
//!
//! the waiting readings are also held in memory, so a forwarding pass never rereads the file. How far
//! the forwarder has got is kept in a small cursor file beside the spool (`<generation> <offset>`).
//! The cursor is saved after a batch rather than after every reading. The file itself is only
//! rewritten once enough has been consumed, so forwarding a long backlog does not rewrite the whole
//! spool for each reading. A crash can send the last unsaved batch again, never lose one.
//!
//! the spool is capped by bytes and by age. When a cap is hit the oldest readings are dropped first
//! and the count is returned so it can be logged.

use std::collections::VecDeque;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use crate::fsutil;

const HEADER: &str = "#phaemos-spool ";
/// the spool file is rewritten once this much of its front has been consumed.
const COMPACT_BYTES: u64 = 1024 * 1024;
/// the rejected file is rotated once it passes this size, so it cannot fill the disk either.
/// the API honours `observed_at` up to seven days back and refuses an older one (`observed_at_too_old`). A
/// reading older than this is dropped and counted, because stamping a week-old reading as arriving now would
/// put it in the wrong place in the history. An hour is left off so a reading never crosses the line on the way.
const OBSERVED_MAX_AGE_SECS: u64 = 7 * 24 * 3600 - 3600;
const REJECTED_MAX_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Copy, Debug)]
pub struct Limits {
    pub max_bytes: u64,
    pub max_age_secs: u64,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_bytes: 8 * 1024 * 1024,
            max_age_secs: 7 * 24 * 3600,
        }
    }
}

/// a forward jump of the wall clock larger than this is not believed at once.
const JUMP_SECS: u64 = 3600;
/// a jump is believed once it has held, still consistent, for this long (on the monotonic clock).
const CONFIRM_SECS: u64 = 60;

/// guards the age cap against a wall clock that jumps. A clock that steps forward by years (a
/// Raspberry Pi with no real-time clock being set by the network or a bad time source) would make
/// every spooled reading look old and drop the lot. The wall clock is compared with the monotonic
/// clock: a jump of more than an hour is ignored (the time is taken as the last good time plus the
/// monotonic time since) until a later reading, at least a minute on, shows the new time has held.
#[derive(Default)]
pub struct ClockGuard {
    anchor_wall: Option<u64>,
    anchor_mono: u64,
    pending: Option<(u64, u64)>,
}

impl ClockGuard {
    /// returns the wall time to judge ages with. `mono` is seconds on a clock that only moves forward.
    pub fn trusted(&mut self, wall: u64, mono: u64) -> u64 {
        let Some(anchor_wall) = self.anchor_wall else {
            self.anchor_wall = Some(wall);
            self.anchor_mono = mono;
            return wall;
        };
        let expected = anchor_wall.saturating_add(mono.saturating_sub(self.anchor_mono));
        if wall.abs_diff(expected) <= JUMP_SECS {
            self.anchor_wall = Some(wall);
            self.anchor_mono = mono;
            self.pending = None;
            return wall;
        }
        match self.pending {
            Some((seen_wall, seen_mono)) if mono.saturating_sub(seen_mono) >= CONFIRM_SECS => {
                let consistent =
                    wall.abs_diff(seen_wall.saturating_add(mono - seen_mono)) <= JUMP_SECS;
                if consistent {
                    self.anchor_wall = Some(wall);
                    self.anchor_mono = mono;
                    self.pending = None;
                    return wall;
                }
                self.pending = Some((wall, mono));
            }
            Some(_) => {}
            None => self.pending = Some((wall, mono)),
        }
        expected
    }
}

pub struct Entry {
    pub ts: u64,
    pub line: String,
    size: u64,
}

pub struct Spool {
    path: PathBuf,
    cursor_path: PathBuf,
    rejected_path: PathBuf,
    limits: Limits,
    generation: u64,
    header_len: u64,
    /// file offset of the first reading not yet consumed.
    consumed: u64,
    /// the offset last written to the cursor file.
    saved: u64,
    file_len: u64,
    live_bytes: u64,
    entries: VecDeque<Entry>,
    guard: ClockGuard,
    started: Instant,
}

fn record(ts: u64, line: &str) -> String {
    format!("{ts}\t{line}\n")
}

fn header_line(generation: u64) -> String {
    format!("{HEADER}{generation}\n")
}

fn sibling(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(suffix);
    PathBuf::from(name)
}

impl Spool {
    /// opens the spool, creating it and its folder if needed. A spool from before the header
    /// existed is read and rewritten in the new format.
    ///
    /// returns the spool and the number of readings dropped on opening because they were over a cap.
    ///
    /// # Errors
    ///
    /// returns any error from creating, reading or writing the files.
    pub fn open(path: impl AsRef<Path>, limits: Limits, now: u64) -> io::Result<(Self, usize)> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            fsutil::ensure_private_dir(parent)?;
        }
        let mut spool = Self {
            cursor_path: sibling(&path, ".cursor"),
            rejected_path: sibling(&path, ".rejected"),
            path,
            limits,
            generation: 1,
            header_len: 0,
            consumed: 0,
            saved: 0,
            file_len: 0,
            live_bytes: 0,
            entries: VecDeque::new(),
            guard: ClockGuard::default(),
            started: Instant::now(),
        };
        let mut rewrite = false;
        if spool.path.exists() {
            rewrite = spool.load(now)?;
        } else {
            spool.write_fresh()?;
        }
        let dropped = spool.expire(now);
        if rewrite || dropped > 0 {
            spool.compact()?;
        }
        Ok((spool, dropped))
    }

    fn load(&mut self, now: u64) -> io::Result<bool> {
        let meta = fs::symlink_metadata(&self.path)?;
        if meta.file_type().is_symlink() || !meta.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                format!("{} is a link or not a regular file", self.path.display()),
            ));
        }
        let mut bytes = Vec::new();
        File::open(&self.path)?.read_to_end(&mut bytes)?;
        // a crash in the middle of an append leaves a last line with no newline. It is not a
        // whole reading, so it is cut off.
        let whole = bytes.iter().rposition(|&b| b == b'\n').map_or(0, |i| i + 1);
        if whole < bytes.len() {
            eprintln!(
                "spool: cut off {} bytes of an unfinished last line",
                bytes.len() - whole
            );
            bytes.truncate(whole);
            OpenOptions::new()
                .write(true)
                .open(&self.path)?
                .set_len(whole as u64)?;
        }
        // the bytes are split on newlines first and each line is converted on its own, so every
        // offset below counts raw bytes and agrees with the cursor check
        let mut lines = bytes.split_inclusive(|&b| b == b'\n').peekable();
        let mut offset = 0u64;
        let mut legacy = true;
        if let Some(first) = lines.peek() {
            let text = String::from_utf8_lossy(first);
            if let Some(generation) = text.trim_end().strip_prefix(HEADER.trim_end()) {
                if let Ok(generation) = generation.trim().parse::<u64>() {
                    self.generation = generation;
                    self.header_len = first.len() as u64;
                    offset = self.header_len;
                    legacy = false;
                    lines.next();
                }
            }
        }
        let start = if legacy {
            0
        } else {
            self.read_cursor(offset, bytes.len() as u64, &bytes)
        };
        self.consumed = start;
        self.saved = start;
        let mut position = offset;
        for raw in lines {
            let size = raw.len() as u64;
            if position >= start {
                let text = String::from_utf8_lossy(raw);
                if !text.trim().is_empty() {
                    let (ts, line) = match text.trim_end().split_once('\t') {
                        Some((ts, line)) if ts.parse::<u64>().is_ok() => {
                            (ts.parse().unwrap_or(now), line)
                        }
                        _ => (now, text.trim()),
                    };
                    self.live_bytes += size;
                    self.entries.push_back(Entry {
                        ts,
                        line: line.to_string(),
                        size,
                    });
                }
            }
            position += size;
        }
        self.file_len = position;
        Ok(legacy)
    }

    /// the saved cursor if it belongs to this file and points at the start of a record, else the
    /// start of the records: sending a few readings twice is better than losing any.
    fn read_cursor(&self, header_len: u64, file_len: u64, bytes: &[u8]) -> u64 {
        let Ok(text) = fs::read_to_string(&self.cursor_path) else {
            return header_len;
        };
        let mut parts = text.split_whitespace();
        let (Some(generation), Some(offset)) = (parts.next(), parts.next()) else {
            return header_len;
        };
        let (Ok(generation), Ok(offset)) = (generation.parse::<u64>(), offset.parse::<u64>())
        else {
            return header_len;
        };
        let aligned = offset == header_len
            || (offset > header_len
                && offset <= file_len
                && bytes.get(usize::try_from(offset - 1).unwrap_or(usize::MAX)) == Some(&b'\n'));
        if generation == self.generation && aligned {
            offset
        } else {
            header_len
        }
    }

    fn write_fresh(&mut self) -> io::Result<()> {
        let header = header_line(self.generation);
        let mut file = fsutil::create_private_new(&self.path)?;
        file.write_all(header.as_bytes())?;
        file.sync_data()?;
        self.header_len = header.len() as u64;
        self.consumed = self.header_len;
        self.saved = self.header_len;
        self.file_len = self.header_len;
        Ok(())
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    #[must_use]
    pub fn live_bytes(&self) -> u64 {
        self.live_bytes
    }

    #[must_use]
    pub fn front(&self) -> Option<&Entry> {
        self.entries.front()
    }

    /// the oldest `n` waiting readings, oldest first.
    #[must_use]
    pub fn front_lines(&self, n: usize) -> Vec<String> {
        self.entries
            .iter()
            .take(n)
            .map(|e| e.line.clone())
            .collect()
    }

    #[must_use]
    pub fn lines(&self) -> Vec<String> {
        self.entries.iter().map(|e| e.line.clone()).collect()
    }

    /// appends one reading and syncs it to disk, then drops the oldest readings if a cap is
    /// passed. Returns how many were dropped.
    ///
    /// # Errors
    ///
    /// returns any error from writing or syncing the file.
    pub fn push(&mut self, line: &str, now: u64) -> io::Result<usize> {
        let line = line.trim();
        let text = record(now, line);
        let mut file = fsutil::open_private_append(&self.path)?;
        file.write_all(text.as_bytes())?;
        file.sync_data()?;
        let size = text.len() as u64;
        self.file_len += size;
        self.live_bytes += size;
        self.entries.push_back(Entry {
            ts: now,
            line: line.to_string(),
            size,
        });
        let dropped = self.expire(now);
        if dropped > 0 || self.consumed - self.header_len >= COMPACT_BYTES {
            self.compact_if_due()?;
        }
        Ok(dropped)
    }

    /// drops readings over the byte cap or older than the age cap, oldest first. Returns how many.
    pub fn expire(&mut self, now: u64) -> usize {
        let now = self.guard.trusted(now, self.started.elapsed().as_secs());
        let mut dropped = 0;
        while let Some(front) = self.entries.front() {
            let too_old =
                now.saturating_sub(front.ts) > self.limits.max_age_secs.min(OBSERVED_MAX_AGE_SECS);
            let too_big = self.live_bytes > self.limits.max_bytes;
            if !(too_old || too_big) {
                break;
            }
            self.pop_front();
            dropped += 1;
        }
        dropped
    }

    /// takes the oldest reading off the queue. Call `commit` to make that survive a restart.
    pub fn pop_front(&mut self) -> Option<Entry> {
        let entry = self.entries.pop_front()?;
        self.consumed += entry.size;
        self.live_bytes -= entry.size;
        Some(entry)
    }

    /// moves the oldest reading to the rejected file with the API's status and the time, then
    /// takes it off the queue.
    ///
    /// # Errors
    ///
    /// returns any error from writing the rejected file. The reading stays queued then.
    pub fn reject(&mut self, status: u16, code: &str, now: u64) -> io::Result<()> {
        let Some(front) = self.entries.front() else {
            return Ok(());
        };
        if fs::metadata(&self.rejected_path).map_or(0, |m| m.len()) > REJECTED_MAX_BYTES {
            fs::rename(&self.rejected_path, sibling(&self.rejected_path, ".old"))?;
        }
        let mut file = fsutil::open_private_append(&self.rejected_path)?;
        writeln!(
            file,
            "{now}\t{status}\t{code}\t{}\t{}",
            front.ts, front.line
        )?;
        file.sync_data()?;
        self.pop_front();
        Ok(())
    }

    /// makes what has been consumed survive a restart: rewrites the file when it is empty or a
    /// good deal of its front is consumed, otherwise saves the cursor.
    ///
    /// # Errors
    ///
    /// returns any error from writing the files.
    pub fn commit(&mut self) -> io::Result<()> {
        if self.consumed == self.saved {
            return Ok(());
        }
        if self.entries.is_empty() || self.consumed - self.header_len >= COMPACT_BYTES {
            return self.compact();
        }
        self.write_cursor()
    }

    fn compact_if_due(&mut self) -> io::Result<()> {
        if self.entries.is_empty() || self.consumed - self.header_len >= COMPACT_BYTES {
            self.compact()
        } else {
            Ok(())
        }
    }

    fn write_cursor(&mut self) -> io::Result<()> {
        let temp = sibling(&self.cursor_path, ".tmp");
        {
            let mut file = fsutil::create_private_new(&temp)?;
            writeln!(file, "{} {}", self.generation, self.consumed)?;
            file.sync_data()?;
        }
        fs::rename(&temp, &self.cursor_path)?;
        self.saved = self.consumed;
        Ok(())
    }

    /// writes the waiting readings to a new file under the next generation and renames it over the
    /// spool. A cursor left from the old generation no longer matches, so a crash between the
    /// rename and the cursor write cannot point into the wrong place.
    fn compact(&mut self) -> io::Result<()> {
        // a header written by someone else can hold the largest number: start again at 1 then
        let generation = self.generation.checked_add(1).unwrap_or(1);
        let header = header_line(generation);
        let temp = sibling(&self.path, ".tmp");
        let mut written = header.len() as u64;
        {
            let mut file = fsutil::create_private_new(&temp)?;
            file.write_all(header.as_bytes())?;
            for entry in &mut self.entries {
                let text = record(entry.ts, &entry.line);
                file.write_all(text.as_bytes())?;
                // the record written may differ in length from the one read (a damaged line is
                // rewritten with replacement characters), so the sizes are brought up to date
                entry.size = text.len() as u64;
                written += entry.size;
            }
            file.sync_data()?;
        }
        fs::rename(&temp, &self.path)?;
        self.live_bytes = self.entries.iter().map(|e| e.size).sum();
        self.generation = generation;
        self.header_len = header.len() as u64;
        self.consumed = self.header_len;
        self.file_len = written;
        self.write_cursor()
    }
}

#[cfg(test)]
mod tests {
    use super::{ClockGuard, Limits, Spool};
    use std::path::PathBuf;

    fn temp_spool(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir.join("spool.jsonl")
    }

    fn open(path: &PathBuf) -> Spool {
        Spool::open(path, Limits::default(), 1000).unwrap().0
    }

    fn reading(id: &str) -> String {
        format!(r#"{{"device_id":"{id}"}}"#)
    }

    #[test]
    fn keeps_readings_in_order() {
        let mut spool = open(&temp_spool("order"));
        spool.push(&reading("a"), 1000).unwrap();
        spool.push(&reading("b"), 1001).unwrap();
        assert_eq!(spool.lines(), vec![reading("a"), reading("b")]);
    }

    #[test]
    fn pop_and_commit_survive_a_restart() {
        let path = temp_spool("restart");
        let mut spool = open(&path);
        for id in ["a", "b", "c"] {
            spool.push(&reading(id), 1000).unwrap();
        }
        spool.pop_front();
        spool.pop_front();
        spool.commit().unwrap();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("c")]);
    }

    #[test]
    fn uncommitted_pops_are_sent_again_not_lost() {
        let path = temp_spool("uncommitted");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        spool.push(&reading("b"), 1000).unwrap();
        spool.pop_front();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("a"), reading("b")]);
    }

    #[test]
    fn cursor_without_compaction_is_used() {
        let path = temp_spool("cursor");
        let mut spool = open(&path);
        for id in ["a", "b", "c"] {
            spool.push(&reading(id), 1000).unwrap();
        }
        spool.pop_front();
        spool.commit().unwrap();
        // the file is not rewritten for one pop: the cursor alone records it
        let on_disk = std::fs::read_to_string(&path).unwrap();
        assert!(on_disk.contains(r#""a""#));
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("b"), reading("c")]);
    }

    #[test]
    fn stale_cursor_after_a_rewrite_is_ignored() {
        let path = temp_spool("stale");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        spool.push(&reading("b"), 1000).unwrap();
        spool.pop_front();
        spool.commit().unwrap(); // cursor of generation 1
        let cursor = std::fs::read_to_string(path.with_extension("jsonl.cursor")).unwrap();
        spool.pop_front();
        spool.commit().unwrap(); // empty: rewritten as generation 2
        spool.push(&reading("c"), 1000).unwrap();
        drop(spool);
        // put the old cursor back, as if the crash came before the new one was written
        std::fs::write(path.with_extension("jsonl.cursor"), cursor).unwrap();
        assert_eq!(open(&path).lines(), vec![reading("c")]);
    }

    #[test]
    fn byte_cap_drops_oldest_first_and_counts() {
        let path = temp_spool("bytes");
        let limits = Limits {
            max_bytes: 120,
            max_age_secs: 1_000_000,
        };
        let (mut spool, _) = Spool::open(&path, limits, 1000).unwrap();
        let mut dropped = 0;
        for i in 0..10 {
            dropped += spool.push(&reading(&format!("n{i}")), 1000).unwrap();
        }
        assert!(dropped > 0);
        assert!(spool.live_bytes() <= 120);
        assert_eq!(spool.lines().last().unwrap(), &reading("n9"));
        assert_eq!(spool.len() + dropped, 10);
        drop(spool);
        let (again, _) = Spool::open(&path, limits, 1000).unwrap();
        assert_eq!(again.len(), 10 - dropped);
    }

    #[test]
    fn age_cap_drops_old_readings() {
        let path = temp_spool("age");
        let limits = Limits {
            max_bytes: 1 << 20,
            max_age_secs: 100,
        };
        let (mut spool, _) = Spool::open(&path, limits, 1000).unwrap();
        spool.push(&reading("old"), 1000).unwrap();
        spool.push(&reading("new"), 1190).unwrap();
        assert_eq!(spool.lines(), vec![reading("new")]);
        assert_eq!(spool.expire(1400), 1);
        assert!(spool.is_empty());
    }

    #[test]
    fn age_cap_applies_when_opening() {
        let path = temp_spool("age-open");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        drop(spool);
        let limits = Limits {
            max_bytes: 1 << 20,
            max_age_secs: 10,
        };
        let (spool, dropped) = Spool::open(&path, limits, 5000).unwrap();
        assert_eq!((dropped, spool.len()), (1, 0));
    }

    #[test]
    fn old_format_spool_is_read_and_converted() {
        let path = temp_spool("legacy");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, format!("{}\n\n{}\n", reading("a"), reading("b"))).unwrap();
        let mut spool = open(&path);
        assert_eq!(spool.lines(), vec![reading("a"), reading("b")]);
        assert_eq!(spool.front().unwrap().ts, 1000);
        spool.push(&reading("c"), 1001).unwrap();
        drop(spool);
        assert_eq!(open(&path).lines().len(), 3);
    }

    #[test]
    fn unfinished_last_line_is_cut_off() {
        let path = temp_spool("torn");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        drop(spool);
        let mut text = std::fs::read_to_string(&path).unwrap();
        text.push_str("1000\t{\"device_id\":\"hal");
        std::fs::write(&path, text).unwrap();
        let mut spool = open(&path);
        assert_eq!(spool.lines(), vec![reading("a")]);
        spool.push(&reading("b"), 1001).unwrap();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("a"), reading("b")]);
    }

    #[test]
    fn reject_moves_the_line_with_status_and_time() {
        let path = temp_spool("reject");
        let mut spool = open(&path);
        spool.push(&reading("bad"), 1000).unwrap();
        spool.push(&reading("good"), 1000).unwrap();
        spool.reject(422, "invalid_reading", 2000).unwrap();
        spool.commit().unwrap();
        assert_eq!(spool.lines(), vec![reading("good")]);
        let rejected = std::fs::read_to_string(path.with_extension("jsonl.rejected")).unwrap();
        assert_eq!(
            rejected,
            format!("2000\t422\tinvalid_reading\t1000\t{}\n", reading("bad"))
        );
    }

    #[test]
    fn many_pops_compact_without_losing_the_rest() {
        let path = temp_spool("compact");
        let mut spool = open(&path);
        let big = format!(r#"{{"device_id":"{}"}}"#, "x".repeat(50_000));
        for _ in 0..25 {
            spool.push(&big, 1000).unwrap();
        }
        spool.push(&reading("tail"), 1000).unwrap();
        for _ in 0..25 {
            spool.pop_front();
        }
        spool.commit().unwrap();
        let size = std::fs::metadata(&path).unwrap().len();
        assert!(size < 1000, "file was not rewritten: {size}");
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("tail")]);
    }

    #[test]
    fn largest_generation_in_a_header_does_not_panic() {
        let path = temp_spool("hostile-gen");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        drop(spool);
        let text = std::fs::read_to_string(&path).unwrap();
        let hostile = text.replacen("#phaemos-spool 1", "#phaemos-spool 18446744073709551615", 1);
        assert_ne!(hostile, text);
        std::fs::write(&path, hostile).unwrap();
        let mut spool = open(&path);
        spool.pop_front();
        spool.commit().unwrap(); // empty: rewritten, which adds one to the generation
        spool.push(&reading("b"), 1001).unwrap();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("b")]);
    }

    #[test]
    fn invalid_utf8_does_not_misalign_the_cursor() {
        let path = temp_spool("lossy");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        spool.push(&reading("b"), 1000).unwrap();
        spool.push(&reading("c"), 1000).unwrap();
        drop(spool);
        // damage the first record with bytes that are not UTF-8, keeping the newline
        let mut bytes = std::fs::read(&path).unwrap();
        let first = bytes.iter().position(|&b| b == b'\n').unwrap() + 1;
        bytes.splice(first + 8..first + 9, [0xFF, 0xFE, 0xFD]);
        std::fs::write(&path, &bytes).unwrap();
        let mut spool = open(&path);
        assert_eq!(spool.len(), 3);
        spool.pop_front();
        spool.commit().unwrap();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("b"), reading("c")]);
        // and after a rewrite the cursor still lines up
        let mut spool = open(&path);
        spool.pop_front();
        spool.commit().unwrap();
        drop(spool);
        assert_eq!(open(&path).lines(), vec![reading("c")]);
    }

    #[test]
    #[cfg(unix)]
    fn files_are_private_and_a_linked_spool_is_refused() {
        use std::os::unix::fs::PermissionsExt;
        let path = temp_spool("private");
        let mut spool = open(&path);
        spool.push(&reading("a"), 1000).unwrap();
        spool.reject(400, "-", 1001).unwrap();
        spool.push(&reading("b"), 1000).unwrap();
        spool.pop_front();
        spool.commit().unwrap();
        let dir = path.parent().unwrap();
        assert_eq!(
            std::fs::metadata(dir).unwrap().permissions().mode() & 0o777,
            0o700
        );
        for entry in std::fs::read_dir(dir).unwrap() {
            let entry = entry.unwrap();
            let mode = entry.metadata().unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600, "{:?}", entry.path());
        }
        drop(spool);
        let real = dir.join("elsewhere");
        std::fs::write(&real, "").unwrap();
        let linked = dir.join("linked.jsonl");
        std::os::unix::fs::symlink(&real, &linked).unwrap();
        assert!(Spool::open(&linked, Limits::default(), 1000).is_err());
    }

    #[test]
    fn a_forward_clock_jump_is_not_believed_at_once() {
        let mut guard = ClockGuard::default();
        assert_eq!(guard.trusted(1_000_000, 0), 1_000_000);
        assert_eq!(guard.trusted(1_000_010, 10), 1_000_010);
        // ten years forward in one step: judged by the last good time plus the time since
        let jumped = 1_000_010 + 10 * 365 * 86_400;
        assert_eq!(guard.trusted(jumped, 20), 1_000_020);
        assert_eq!(guard.trusted(jumped + 30, 50), 1_000_050);
        // a minute later it has held, so it is believed
        assert_eq!(guard.trusted(jumped + 90, 110), jumped + 90);
        assert_eq!(guard.trusted(jumped + 100, 120), jumped + 100);
    }

    #[test]
    fn a_clock_that_keeps_changing_is_never_believed() {
        let mut guard = ClockGuard::default();
        guard.trusted(1_000_000, 0);
        let far = 1_000_000 + 400 * 86_400;
        assert_eq!(guard.trusted(far, 10), 1_000_010);
        assert_eq!(guard.trusted(far + 400 * 86_400, 100), 1_000_100);
        assert_eq!(guard.trusted(far, 200), 1_000_200);
    }

    #[test]
    fn a_backward_jump_does_not_age_anything_either() {
        let mut guard = ClockGuard::default();
        guard.trusted(1_000_000, 0);
        assert_eq!(guard.trusted(500_000, 10), 1_000_010);
    }

    #[test]
    fn a_forward_jump_does_not_drop_the_spool() {
        let path = temp_spool("jump");
        let limits = Limits {
            max_bytes: 1 << 20,
            max_age_secs: 7 * 86_400,
        };
        let (mut spool, _) = Spool::open(&path, limits, 1_000_000).unwrap();
        spool.push(&reading("a"), 1_000_000).unwrap();
        // the clock steps forward a year: nothing is dropped on this pass
        assert_eq!(spool.expire(1_000_000 + 365 * 86_400), 0);
        assert_eq!(spool.len(), 1);
    }

    #[test]
    fn a_reading_too_old_for_observed_at_is_dropped_and_counted_even_with_a_longer_cap() {
        let path = temp_spool("observed-cap");
        // the cap asked for is 30 days, but the API refuses an observed_at older than seven days
        let limits = Limits {
            max_bytes: 1 << 20,
            max_age_secs: 30 * 86_400,
        };
        let day = 86_400;
        let (mut spool, _) = Spool::open(&path, limits, 100 * day).unwrap();
        spool
            .push(&reading("old"), 100 * day - 7 * day - 60)
            .unwrap_or(0);
        drop(spool);
        // a spool written earlier holds readings of several ages
        std::fs::remove_file(&path).unwrap();
        let (mut spool, _) = Spool::open(&path, limits, 94 * day).unwrap();
        for (id, age) in [("old", 7 * day), ("edge", 6 * day), ("new", 60)] {
            spool.push(&reading(id), 94 * day + 6 * day - age).unwrap();
        }
        drop(spool);
        let (spool, dropped) = Spool::open(&path, limits, 100 * day).unwrap();
        assert_eq!(
            (dropped, spool.lines()),
            (1, vec![reading("edge"), reading("new")])
        );
        drop(spool);
        let (spool, dropped) = Spool::open(&path, limits, 101 * day).unwrap();
        assert_eq!((dropped, spool.lines()), (1, vec![reading("new")]));
    }
}
