//! file helpers that keep the gateway's files private and refuse planted links.
//!
//! the spool holds readings and a boot counter, so its folder is created 0700 and a folder that other
//! users can write to is refused. Files are created with mode 0600. Temporary files are opened with
//! `create_new`, which fails if anything (a symlink included) already sits at the name, so a link planted
//! at a temporary name is never followed.

use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::Path;

#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt};

/// the user id this process runs as, read from the owner of `/proc/self`. `None` where that is not
/// available, in which case owner checks are skipped.
#[must_use]
pub fn current_uid() -> Option<u32> {
    #[cfg(unix)]
    {
        fs::metadata("/proc/self").ok().map(|m| m.uid())
    }
    #[cfg(not(unix))]
    {
        None
    }
}

/// creates the folder (and its parents) with mode 0700 when it is missing, then refuses it if it is
/// a symlink, is not a folder, is owned by someone else or can be written by group or others.
///
/// # Errors
///
/// returns an error describing why the folder cannot be trusted or created.
pub fn ensure_private_dir(path: &Path) -> io::Result<()> {
    if path.as_os_str().is_empty() {
        return Ok(());
    }
    #[cfg(unix)]
    {
        if fs::symlink_metadata(path).is_err() {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(path)?;
        }
        let meta = fs::symlink_metadata(path)?;
        if meta.file_type().is_symlink() || !meta.is_dir() {
            return Err(refuse(
                path,
                "is not a plain folder (it is a link or a file)",
            ));
        }
        if meta.mode() & 0o022 != 0 {
            return Err(refuse(
                path,
                "can be written by other users: run chmod 700 on it",
            ));
        }
        if let Some(uid) = current_uid() {
            if meta.uid() != uid {
                return Err(refuse(path, "belongs to another user"));
            }
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        fs::create_dir_all(path)
    }
}

fn refuse(path: &Path, why: &str) -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        format!("folder {} {why}", path.display()),
    )
}

/// creates a new file with mode 0600, failing if the name is taken. A leftover file or planted link at
/// the name is removed first (removing a link removes the link and not its target).
///
/// # Errors
///
/// returns any error from removing or creating the file.
pub fn create_private_new(path: &Path) -> io::Result<File> {
    if fs::symlink_metadata(path).is_ok() {
        fs::remove_file(path)?;
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    options.open(path)
}

/// opens a file for appending, creating it with mode 0600. A symlink or anything that is not a plain
/// file at the name is refused.
///
/// # Errors
///
/// returns an error when the name is a link or not a regular file or the open fails.
pub fn open_private_append(path: &Path) -> io::Result<File> {
    match fs::symlink_metadata(path) {
        Ok(meta) => {
            if meta.file_type().is_symlink() || !meta.is_file() {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    format!("{} is a link or not a regular file", path.display()),
                ));
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    let mut options = OpenOptions::new();
    options.append(true).create(true);
    #[cfg(unix)]
    options.mode(0o600);
    options.open(path)
}

/// the mode bits of a file, for tests and checks.
///
/// # Errors
///
/// returns any error from reading the metadata.
#[cfg(unix)]
pub fn mode_of(path: &Path) -> io::Result<u32> {
    Ok(fs::metadata(path)?.permissions().mode() & 0o777)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-fs-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    #[cfg(unix)]
    fn new_folder_is_0700_and_files_0600() {
        let dir = temp("modes").join("a").join("b");
        ensure_private_dir(&dir).unwrap();
        assert_eq!(mode_of(&dir).unwrap(), 0o700);
        let file = dir.join("f");
        drop(create_private_new(&file).unwrap());
        assert_eq!(mode_of(&file).unwrap(), 0o600);
        let log = dir.join("log");
        drop(open_private_append(&log).unwrap());
        assert_eq!(mode_of(&log).unwrap(), 0o600);
    }

    #[test]
    #[cfg(unix)]
    fn folder_others_can_write_is_refused() {
        let dir = temp("open");
        fs::create_dir_all(&dir).unwrap();
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o777)).unwrap();
        assert!(ensure_private_dir(&dir).is_err());
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o770)).unwrap();
        assert!(ensure_private_dir(&dir).is_err());
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).unwrap();
        assert!(ensure_private_dir(&dir).is_ok());
    }

    #[test]
    #[cfg(unix)]
    fn symlinked_folder_is_refused() {
        let base = temp("link");
        fs::create_dir_all(&base).unwrap();
        let real = base.join("real");
        fs::create_dir(&real).unwrap();
        fs::set_permissions(&real, fs::Permissions::from_mode(0o700)).unwrap();
        let link = base.join("link");
        std::os::unix::fs::symlink(&real, &link).unwrap();
        assert!(ensure_private_dir(&link).is_err());
    }

    #[test]
    #[cfg(unix)]
    fn planted_link_at_a_temp_name_is_replaced_not_followed() {
        let base = temp("plant");
        ensure_private_dir(&base).unwrap();
        let victim = base.join("victim");
        fs::write(&victim, "keep me").unwrap();
        let temp_name = base.join("spool.tmp");
        std::os::unix::fs::symlink(&victim, &temp_name).unwrap();
        let mut file = create_private_new(&temp_name).unwrap();
        io::Write::write_all(&mut file, b"new").unwrap();
        assert_eq!(fs::read_to_string(&victim).unwrap(), "keep me");
        assert_eq!(fs::read_to_string(&temp_name).unwrap(), "new");
    }

    #[test]
    #[cfg(unix)]
    fn append_refuses_a_link() {
        let base = temp("append");
        ensure_private_dir(&base).unwrap();
        let victim = base.join("victim");
        fs::write(&victim, "x").unwrap();
        let link = base.join("log");
        std::os::unix::fs::symlink(&victim, &link).unwrap();
        assert!(open_private_append(&link).is_err());
        assert_eq!(fs::read_to_string(&victim).unwrap(), "x");
    }
}
