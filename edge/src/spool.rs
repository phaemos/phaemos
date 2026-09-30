//! A disk-backed queue of readings waiting to be forwarded.
//!
//! Each reading is one line in an append-only file, flushed to disk before it is
//! acknowledged, so a power cut or network outage never loses telemetry.

use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

pub struct Spool {
    path: PathBuf,
}

impl Spool {
    /// Opens the spool file, creating it and its folder if needed.
    ///
    /// # Errors
    ///
    /// Returns any error from creating the folder or the file.
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            fs::create_dir_all(parent)?;
        }
        OpenOptions::new().create(true).append(true).open(&path)?;
        Ok(Self { path })
    }

    /// Appends one reading and flushes it to disk.
    ///
    /// # Errors
    ///
    /// Returns any error from writing or syncing the file.
    pub fn push(&self, line: &str) -> io::Result<()> {
        let mut file = OpenOptions::new().append(true).open(&self.path)?;
        writeln!(file, "{}", line.trim())?;
        file.sync_data()
    }

    /// Every reading still waiting, oldest first.
    ///
    /// # Errors
    ///
    /// Returns any error from reading the file.
    pub fn pending(&self) -> io::Result<Vec<String>> {
        BufReader::new(File::open(&self.path)?)
            .lines()
            .filter(|line| line.as_ref().map_or(true, |l| !l.trim().is_empty()))
            .collect()
    }

    /// Removes the oldest `count` readings once they have been forwarded. The rest
    /// is written to a temporary file and renamed over the spool, so a crash mid-way
    /// leaves either the old or the new spool, never a half-written one.
    ///
    /// # Errors
    ///
    /// Returns any error from reading, writing or renaming the files.
    pub fn ack(&self, count: usize) -> io::Result<()> {
        if count == 0 {
            return Ok(());
        }
        let remaining: Vec<String> = self.pending()?.into_iter().skip(count).collect();
        let temp = self.path.with_extension("tmp");
        {
            let mut file = File::create(&temp)?;
            for line in &remaining {
                writeln!(file, "{line}")?;
            }
            file.sync_data()?;
        }
        fs::rename(&temp, &self.path)
    }
}

#[cfg(test)]
mod tests {
    use super::Spool;
    use std::path::PathBuf;

    fn temp_spool(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir.join("spool.jsonl")
    }

    #[test]
    fn keeps_readings_in_order() {
        let spool = Spool::open(temp_spool("order")).unwrap();
        spool.push(r#"{"device_id":"a"}"#).unwrap();
        spool.push(r#"{"device_id":"b"}"#).unwrap();
        assert_eq!(
            spool.pending().unwrap(),
            vec![r#"{"device_id":"a"}"#, r#"{"device_id":"b"}"#]
        );
    }

    #[test]
    fn ack_drops_only_forwarded_readings() {
        let spool = Spool::open(temp_spool("ack")).unwrap();
        for id in ["a", "b", "c"] {
            spool.push(&format!(r#"{{"device_id":"{id}"}}"#)).unwrap();
        }
        spool.ack(2).unwrap();
        assert_eq!(spool.pending().unwrap(), vec![r#"{"device_id":"c"}"#]);
        spool.ack(5).unwrap();
        assert!(spool.pending().unwrap().is_empty());
    }

    #[test]
    fn survives_a_restart() {
        let path = temp_spool("restart");
        Spool::open(&path)
            .unwrap()
            .push(r#"{"device_id":"a"}"#)
            .unwrap();
        assert_eq!(Spool::open(&path).unwrap().pending().unwrap().len(), 1);
    }
}
