//! command line, key and address handling. Nothing here prints or stores the key anywhere but in
//! the `Config` it returns. `Config` hides it when printed.

use std::fmt;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::fsutil;
use crate::spool::Limits;

pub struct Config {
    pub api_url: String,
    pub api_key: String,
    pub spool: String,
    pub allow_insecure_http: bool,
    pub limits: Limits,
    pub max_line_bytes: usize,
    /// one-line notices for stderr, such as the use of an old variable name.
    pub notices: Vec<String>,
}

impl fmt::Debug for Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Config")
            .field("api_url", &self.api_url)
            .field("api_key", &"<hidden>")
            .field("spool", &self.spool)
            .field("allow_insecure_http", &self.allow_insecure_http)
            .finish_non_exhaustive()
    }
}

/// the key is sent in a header, so it must be one line of visible characters.
fn clean_key(text: &str) -> Result<String, String> {
    let key = text.trim();
    if key.is_empty() {
        return Err("the API key is empty".to_string());
    }
    if !key.bytes().all(|b| b.is_ascii_graphic()) {
        return Err(
            "the API key has a space or a character that is not printable ASCII".to_string(),
        );
    }
    Ok(key.to_string())
}

/// reads the key from a file that only its owner can read. The file is opened once and the checks
/// are made on the open handle, so the file cannot be swapped between the check and the read.
///
/// # Errors
///
/// returns a message (never holding the key) when the file cannot be read, is readable by
/// anyone else, belongs to another user or holds no usable key.
pub fn read_key_file(path: &Path) -> Result<String, String> {
    let mut file =
        File::open(path).map_err(|e| format!("cannot read key file {}: {e}", path.display()))?;
    let meta = file
        .metadata()
        .map_err(|e| format!("cannot read key file {}: {e}", path.display()))?;
    if !meta.is_file() {
        return Err(format!("key file {} is not a regular file", path.display()));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        let mode = meta.permissions().mode() & 0o777;
        if mode & 0o077 != 0 {
            return Err(format!(
                "key file {} has mode {mode:03o}: other users can read it. Run chmod 600 on it",
                path.display()
            ));
        }
        if let Some(uid) = fsutil::current_uid() {
            if meta.uid() != uid {
                return Err(format!(
                    "key file {} belongs to another user",
                    path.display()
                ));
            }
        }
    }
    let mut text = String::new();
    file.read_to_string(&mut text)
        .map_err(|e| format!("cannot read key file {}: {e}", path.display()))?;
    clean_key(&text)
}

/// the private state folder the spool lives in when `--spool` is not given: `STATE_DIRECTORY` (set
/// by systemd), else `$XDG_STATE_HOME/phaemos`, else `$HOME/.local/state/phaemos`. Never the working
/// directory.
///
/// # Errors
///
/// returns a message when none of those is set.
pub fn default_spool(env: &impl Fn(&str) -> Option<String>) -> Result<String, String> {
    let base = if let Some(dir) = env("STATE_DIRECTORY").filter(|d| !d.is_empty()) {
        PathBuf::from(dir.split(':').next().unwrap_or(""))
    } else if let Some(dir) = env("XDG_STATE_HOME").filter(|d| !d.is_empty()) {
        PathBuf::from(dir).join("phaemos")
    } else if let Some(home) = env("HOME").filter(|d| !d.is_empty()) {
        PathBuf::from(home).join(".local/state/phaemos")
    } else {
        return Err("no state folder: set STATE_DIRECTORY or HOME or pass --spool with a path in a private folder".to_string());
    };
    Ok(base.join("spool.jsonl").to_string_lossy().into_owned())
}

/// picks the key from the key file when one is named, else from `PHAEMOS_DEVICE_KEY`.
///
/// # Errors
///
/// returns a message when neither is given or the one given is not usable.
pub fn resolve_key(file: Option<&Path>, env_key: Option<&str>) -> Result<String, String> {
    match (file, env_key) {
        (Some(path), _) => read_key_file(path),
        (None, Some(key)) => clean_key(key),
        (None, None) => Err(
            "give the key in PHAEMOS_DEVICE_KEY or name a file with --key-file (mode 0600)"
                .to_string(),
        ),
    }
}

/// checks the API address. `https://` is always fine, `http://` only when plain HTTP was allowed.
///
/// # Errors
///
/// returns a message when the address is not usable.
pub fn check_api_url(url: &str, allow_insecure_http: bool) -> Result<String, String> {
    let url = url.trim().trim_end_matches('/');
    let rest = if let Some(rest) = url.strip_prefix("https://") {
        rest
    } else if let Some(rest) = url.strip_prefix("http://") {
        if !allow_insecure_http {
            return Err("the API address is http://, which sends the key and the readings unencrypted. Use https:// or pass --allow-insecure-http for bench testing only".to_string());
        }
        rest
    } else {
        return Err("the API address must start with https://".to_string());
    };
    if rest.is_empty() || rest.contains('@') || rest.contains(char::is_whitespace) {
        return Err("the API address has no host, holds credentials or has a space".to_string());
    }
    // the server answers 404 for a path with a trailing slash and never redirects it, so the address is the
    // base only and the gateway adds the route itself
    if let Some((_, path)) = rest.split_once('/') {
        return Err(format!(
            "the API address must be the base address only, for example https://api.example.org. Remove the path /{path} (the gateway adds /api/v1/telemetry itself)"
        ));
    }
    Ok(url.to_string())
}

fn number(flag: &str, value: &str) -> Result<u64, String> {
    value
        .parse()
        .map_err(|_| format!("{flag} needs a whole number"))
}

/// the options that take a value.
const WITH_VALUE: [&str; 8] = [
    "--url",
    "--api-url",
    "--key-file",
    "--api-key-file",
    "--spool",
    "--spool-max-mb",
    "--spool-max-age-hours",
    "--max-line-bytes",
];

/// what the command line asks for.
pub enum Parsed {
    Run(Box<Config>),
    Help,
    Version,
}

pub const HELP: &str = "phaemos-edge: reads readings as JSON lines on standard input, spools them to disk and forwards them to a PHAEMOS server

Usage:
  phaemos-edge --url <address> [options]

Examples:
  PHAEMOS_DEVICE_KEY=<device key> phaemos-edge --url https://api.example.org < readings.jsonl
  cat /dev/ttyUSB0 | phaemos-edge --url https://api.example.org --key-file /etc/phaemos/key

Options:
  --url <address>           the API address, https:// (default: PHAEMOS_URL)
  --key-file <path>         a file holding the device key, readable by its owner only (default: PHAEMOS_DEVICE_KEY_FILE)
  --spool <path>            the spool file (default: STATE_DIRECTORY, else XDG_STATE_HOME/phaemos, else ~/.local/state/phaemos)
  --spool-max-mb <n>        the most the spool keeps, in MiB (default 8)
  --spool-max-age-hours <n> the oldest reading the spool keeps (default 168)
  --max-line-bytes <n>      the longest input line (default 65536)
  --allow-insecure-http     allow plain http:// (bench testing only: the key is not encrypted)
  --version                 print the version
  -h, --help                print this help
  An option may be written --name value or --name=value. --api-url and --api-key-file still work.

The device key comes from PHAEMOS_DEVICE_KEY or a key file, never from a flag, because a flag shows in the process list.
PHAEMOS_API_KEY and PHAEMOS_API_KEY_FILE are the old names and still work with a notice.

Each reading is stamped with the gateway's own boot, seq and observed_at before it is spooled. Readings are sent in batches
when the server has a batch route and one at a time when it has not.

Exit codes (the same meanings as phaemosctl where they apply):
  0  every reading was forwarded or set aside and nothing is left in the spool
  1  a failure: the spool or counter could not be used
  2  a usage error
  3  the server refused the key and readings are left in the spool
  6  the server refused the readings or the counter and readings are left in the spool
  7  the server rate limited the gateway and readings are left in the spool
  8  the server or the network failed and readings are left in the spool
";

fn split_equals(args: &[String]) -> Vec<String> {
    let mut out = Vec::with_capacity(args.len());
    for arg in args {
        match arg.split_once('=') {
            Some((name, value)) if name.starts_with("--") => {
                out.push(name.to_string());
                out.push(value.to_string());
            }
            _ => out.push(arg.clone()),
        }
    }
    out
}

/// parses the command line. `env` looks up an environment variable.
///
/// # Errors
///
/// returns a message for a flag that is unknown, missing its value or not allowed.
pub fn parse(args: &[String], env: impl Fn(&str) -> Option<String>) -> Result<Parsed, String> {
    let mut notices = Vec::new();
    let mut api_url = env("PHAEMOS_URL").filter(|u| !u.is_empty());
    let mut key_file = env("PHAEMOS_DEVICE_KEY_FILE").map(PathBuf::from);
    if key_file.is_none() {
        if let Some(old) = env("PHAEMOS_API_KEY_FILE") {
            notices.push(
                "PHAEMOS_API_KEY_FILE is the old name: use PHAEMOS_DEVICE_KEY_FILE".to_string(),
            );
            key_file = Some(PathBuf::from(old));
        }
    }
    let mut spool: Option<String> = None;
    let mut allow_insecure_http = false;
    let mut limits = Limits::default();
    let mut max_line_bytes = 64 * 1024;
    let args = split_equals(args);
    let mut iter = args.iter();
    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "-h" | "--help" => return Ok(Parsed::Help),
            "--version" => return Ok(Parsed::Version),
            "--allow-insecure-http" => {
                allow_insecure_http = true;
                continue;
            }
            "--api-key" | "--key" => {
                return Err("a key on the command line shows in the process list, so it is not accepted. Use PHAEMOS_DEVICE_KEY or --key-file".to_string());
            }
            _ => {}
        }
        if !WITH_VALUE.contains(&flag.as_str()) {
            return Err(format!("unknown option {flag}. Try --help"));
        }
        let value = iter.next().ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--url" | "--api-url" => api_url = Some(value.clone()),
            "--key-file" | "--api-key-file" => key_file = Some(PathBuf::from(value)),
            "--spool" => spool = Some(value.clone()),
            "--spool-max-mb" => limits.max_bytes = number(flag, value)?.saturating_mul(1024 * 1024),
            "--spool-max-age-hours" => {
                limits.max_age_secs = number(flag, value)?.saturating_mul(3600);
            }
            "--max-line-bytes" => {
                max_line_bytes =
                    usize::try_from(number(flag, value)?).map_err(|_| "too large".to_string())?;
            }
            other => return Err(format!("unknown option {other}. Try --help")),
        }
    }
    let api_url = check_api_url(
        &api_url.ok_or("--url is required (or PHAEMOS_URL)")?,
        allow_insecure_http,
    )?;
    let spool = match spool {
        Some(path) => path,
        None => default_spool(&env)?,
    };
    let mut env_key = env("PHAEMOS_DEVICE_KEY");
    if env_key.is_none() {
        if let Some(old) = env("PHAEMOS_API_KEY") {
            notices.push("PHAEMOS_API_KEY is the old name: use PHAEMOS_DEVICE_KEY".to_string());
            env_key = Some(old);
        }
    }
    let api_key = resolve_key(key_file.as_deref(), env_key.as_deref())?;
    if limits.max_bytes == 0 || max_line_bytes == 0 {
        return Err("the caps must be above zero".to_string());
    }
    Ok(Parsed::Run(Box::new(Config {
        api_url,
        api_key,
        spool,
        allow_insecure_http,
        limits,
        max_line_bytes,
        notices,
    })))
}

#[cfg(test)]
mod tests {
    use super::{check_api_url, parse, read_key_file, resolve_key, Config, Parsed};
    use std::path::PathBuf;

    fn cfg(list: &[String], env: impl Fn(&str) -> Option<String>) -> Result<Config, String> {
        match parse(list, env)? {
            Parsed::Run(config) => Ok(*config),
            _ => Err("not a run".to_string()),
        }
    }

    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| (*s).to_string()).collect()
    }

    fn no_env(_: &str) -> Option<String> {
        None
    }

    fn temp_file(name: &str, content: &str, mode: u32) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-key-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("key");
        std::fs::write(&path, content).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        }
        let _ = mode;
        path
    }

    #[test]
    fn key_on_the_command_line_is_refused_and_not_echoed() {
        let err = cfg(
            &args(&["--api-url", "https://a.b", "--api-key", "s3cret"]),
            no_env,
        )
        .unwrap_err();
        assert!(err.contains("process list"));
        assert!(!err.contains("s3cret"));
        let err = cfg(&args(&["--api-key=s3cret"]), no_env).unwrap_err();
        assert!(!err.contains("s3cret"));
    }

    #[test]
    fn key_comes_from_the_environment() {
        let env = |name: &str| match name {
            "PHAEMOS_DEVICE_KEY" => Some("abc123\n".to_string()),
            "HOME" => Some("/home/gw".to_string()),
            _ => None,
        };
        let config = cfg(&args(&["--api-url", "https://a.b/"]), env).unwrap();
        assert_eq!(config.api_key, "abc123");
        assert_eq!(config.api_url, "https://a.b");
        assert!(!format!("{config:?}").contains("abc123"));
    }

    #[test]
    fn missing_key_is_an_error() {
        assert!(cfg(&args(&["--api-url", "https://a.b"]), no_env).is_err());
    }

    #[test]
    #[cfg(unix)]
    fn key_file_must_be_private() {
        let good = temp_file("good", "filekey\n", 0o600);
        assert_eq!(read_key_file(&good).unwrap(), "filekey");
        for mode in [0o644, 0o640, 0o604] {
            let bad = temp_file("bad", "filekey", mode);
            let err = read_key_file(&bad).unwrap_err();
            assert!(err.contains("chmod 600"), "{mode:o}: {err}");
            assert!(!err.contains("filekey"));
        }
    }

    #[test]
    #[cfg(unix)]
    fn key_file_wins_over_the_environment() {
        let path = temp_file("wins", "fromfile", 0o600);
        assert_eq!(
            resolve_key(Some(&path), Some("fromenv")).unwrap(),
            "fromfile"
        );
    }

    #[test]
    fn key_with_a_newline_or_space_inside_is_refused() {
        assert!(resolve_key(None, Some("a b")).is_err());
        assert!(resolve_key(None, Some("a\nX-Evil: 1")).is_err());
        assert!(resolve_key(None, Some("  ")).is_err());
    }

    #[test]
    fn http_needs_the_flag() {
        assert!(check_api_url("http://10.0.0.2:8000", false).is_err());
        assert_eq!(
            check_api_url("http://10.0.0.2:8000/", true).unwrap(),
            "http://10.0.0.2:8000"
        );
        assert_eq!(
            check_api_url("https://api.example.org", false).unwrap(),
            "https://api.example.org"
        );
        assert!(check_api_url("ftp://x", true).is_err());
        // trailing slashes are stripped and a path is refused with a plain message
        assert_eq!(
            check_api_url("https://api.example.org//", false).unwrap(),
            "https://api.example.org"
        );
        for bad in [
            "https://h/api/v1/telemetry",
            "https://h/api/v1/telemetry/",
            "https://h/api/",
            "http://h:8000/x/",
        ] {
            let err = check_api_url(bad, true).unwrap_err();
            assert!(
                err.contains("base address only") && err.contains("Remove the path"),
                "{bad}: {err}"
            );
        }
        assert!(check_api_url("https://user:pw@host", false).is_err());
        assert!(check_api_url("https://", false).is_err());
    }

    #[test]
    fn flags_and_caps_parse() {
        let env = |name: &str| match name {
            "PHAEMOS_DEVICE_KEY" => Some("k".to_string()),
            "HOME" => Some("/home/gw".to_string()),
            _ => None,
        };
        let config = cfg(
            &args(&[
                "--api-url",
                "http://h",
                "--allow-insecure-http",
                "--spool-max-mb",
                "2",
                "--spool-max-age-hours",
                "1",
                "--max-line-bytes",
                "100",
            ]),
            env,
        )
        .unwrap();
        assert!(config.allow_insecure_http);
        assert_eq!(config.limits.max_bytes, 2 * 1024 * 1024);
        assert_eq!(config.limits.max_age_secs, 3600);
        assert_eq!(config.max_line_bytes, 100);
    }

    #[test]
    fn unknown_flag_and_missing_value() {
        let err = cfg(&args(&["--nope"]), no_env).unwrap_err();
        assert!(err.contains("unknown option --nope"), "{err}");
        assert!(cfg(&args(&["--nope", "1"]), no_env).is_err());
        assert!(cfg(&args(&["--api-url"]), no_env)
            .unwrap_err()
            .contains("needs a value"));
    }

    #[test]
    fn the_spool_defaults_to_a_private_state_folder_and_never_the_working_directory() {
        let home = |n: &str| (n == "HOME").then(|| "/home/gw".to_string());
        assert_eq!(
            super::default_spool(&home).unwrap(),
            "/home/gw/.local/state/phaemos/spool.jsonl"
        );
        let xdg = |n: &str| match n {
            "XDG_STATE_HOME" => Some("/x".to_string()),
            "HOME" => Some("/home/gw".to_string()),
            _ => None,
        };
        assert_eq!(
            super::default_spool(&xdg).unwrap(),
            "/x/phaemos/spool.jsonl"
        );
        let systemd =
            |n: &str| (n == "STATE_DIRECTORY").then(|| "/var/lib/phaemos:/other".to_string());
        assert_eq!(
            super::default_spool(&systemd).unwrap(),
            "/var/lib/phaemos/spool.jsonl"
        );
        assert!(super::default_spool(&no_env).is_err());
    }

    #[test]
    fn spool_flag_overrides_the_default() {
        let env = |n: &str| (n == "PHAEMOS_DEVICE_KEY").then(|| "k".to_string());
        let config = cfg(
            &args(&["--api-url", "https://a.b", "--spool", "/tmp/x/s.jsonl"]),
            env,
        )
        .unwrap();
        assert_eq!(config.spool, "/tmp/x/s.jsonl");
    }

    #[test]
    #[cfg(unix)]
    fn key_file_that_is_a_link_to_a_loose_file_is_judged_by_the_target() {
        let loose = temp_file("linktarget", "filekey", 0o644);
        let link = loose.with_file_name("link");
        std::os::unix::fs::symlink(&loose, &link).unwrap();
        assert!(read_key_file(&link).is_err());
    }

    #[test]
    fn help_and_version_are_answers_and_not_errors() {
        assert!(matches!(
            parse(&args(&["--help"]), no_env),
            Ok(Parsed::Help)
        ));
        assert!(matches!(parse(&args(&["-h"]), no_env), Ok(Parsed::Help)));
        assert!(matches!(
            parse(&args(&["--version"]), no_env),
            Ok(Parsed::Version)
        ));
        // they need no key and no address
        assert!(matches!(
            parse(&args(&["--url", "https://a.b", "--help"]), no_env),
            Ok(Parsed::Help)
        ));
        for needle in [
            "--url",
            "--key-file",
            "PHAEMOS_DEVICE_KEY",
            "Exit codes",
            "--version",
            "Examples:",
        ] {
            assert!(super::HELP.contains(needle), "{needle}");
        }
    }

    #[test]
    fn options_may_use_an_equals_sign() {
        let env = |name: &str| match name {
            "PHAEMOS_DEVICE_KEY" => Some("k".to_string()),
            "HOME" => Some("/home/gw".to_string()),
            _ => None,
        };
        let config = cfg(
            &args(&[
                "--url=https://a.b",
                "--spool-max-mb=3",
                "--spool=/tmp/s.jsonl",
            ]),
            env,
        )
        .unwrap();
        assert_eq!(
            (
                config.api_url.as_str(),
                config.limits.max_bytes,
                config.spool.as_str()
            ),
            ("https://a.b", 3 * 1024 * 1024, "/tmp/s.jsonl")
        );
    }

    #[test]
    fn a_key_given_as_equals_is_still_refused_and_not_echoed() {
        let err = cfg(&args(&["--url", "https://a.b", "--key=s3cret"]), no_env).unwrap_err();
        assert!(err.contains("process list") && !err.contains("s3cret"));
    }

    #[test]
    fn the_address_comes_from_a_flag_then_the_environment() {
        let env = |name: &str| match name {
            "PHAEMOS_URL" => Some("https://from.env".to_string()),
            "PHAEMOS_DEVICE_KEY" => Some("k".to_string()),
            "HOME" => Some("/h".to_string()),
            _ => None,
        };
        assert_eq!(cfg(&args(&[]), env).unwrap().api_url, "https://from.env");
        assert_eq!(
            cfg(&args(&["--url", "https://flag"]), env).unwrap().api_url,
            "https://flag"
        );
        assert_eq!(
            cfg(&args(&["--api-url", "https://old.name"]), env)
                .unwrap()
                .api_url,
            "https://old.name"
        );
        assert!(cfg(&args(&[]), |n: &str| (n == "PHAEMOS_DEVICE_KEY")
            .then(|| "k".to_string()))
        .is_err());
    }

    #[test]
    fn the_old_variable_names_work_with_one_notice_each() {
        let env = |name: &str| match name {
            "PHAEMOS_API_KEY" => Some("oldkey".to_string()),
            "HOME" => Some("/h".to_string()),
            _ => None,
        };
        let config = cfg(&args(&["--url", "https://a.b"]), env).unwrap();
        assert_eq!(config.api_key, "oldkey");
        assert_eq!(
            config.notices,
            vec!["PHAEMOS_API_KEY is the old name: use PHAEMOS_DEVICE_KEY".to_string()]
        );
        let both = |name: &str| match name {
            "PHAEMOS_API_KEY" => Some("oldkey".to_string()),
            "PHAEMOS_DEVICE_KEY" => Some("newkey".to_string()),
            "HOME" => Some("/h".to_string()),
            _ => None,
        };
        let config = cfg(&args(&["--url", "https://a.b"]), both).unwrap();
        assert_eq!(
            (config.api_key.as_str(), config.notices.len()),
            ("newkey", 0)
        );
    }

    #[test]
    #[cfg(unix)]
    fn the_key_file_flag_and_its_old_name_both_work() {
        let path = temp_file("keyfileflag", "filekey", 0o600);
        let env = |n: &str| (n == "HOME").then(|| "/h".to_string());
        for flag in ["--key-file", "--api-key-file"] {
            let config = cfg(
                &args(&["--url", "https://a.b", flag, path.to_str().unwrap()]),
                env,
            )
            .unwrap();
            assert_eq!(config.api_key, "filekey");
        }
    }
}
