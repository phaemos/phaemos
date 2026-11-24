//! `phaemos-edge`: reads readings as JSON lines on stdin (for example from a node's
//! serial bridge), spools them to disk and forwards them to the PHAEMOS API.
//!
//! usage: `PHAEMOS_DEVICE_KEY=KEY phaemos-edge --url https://api.phaemos.com [--spool PATH]`
//!
//! the key is never taken from the command line, because the process list shows it.

mod http;

use std::io::{self, BufReader};
use std::process::ExitCode;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use phaemos_edge::forward::{flush, Flushed, Stop};
use phaemos_edge::input::{read_line, Line};
use phaemos_edge::settings::{Parsed, HELP};
use phaemos_edge::stamp::Stamper;
use phaemos_edge::{backoff, reading, settings, spool::Spool};

/// the longest one forwarding pass runs before the loop goes back to reading input.
const PASS_BUDGET: Duration = Duration::from_secs(2);
/// how many input lines may wait in memory for the loop. A full queue makes the reader wait.
/// The pipe behind it then fills, so this is a few seconds of a busy serial link.
const QUEUE_LINES: usize = 4096;

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let config = match settings::parse(&args, |name| std::env::var(name).ok()) {
        Ok(Parsed::Run(config)) => config,
        Ok(Parsed::Help) => {
            print!("{HELP}");
            return ExitCode::SUCCESS;
        }
        Ok(Parsed::Version) => {
            println!("phaemos-edge {}", env!("CARGO_PKG_VERSION"));
            return ExitCode::SUCCESS;
        }
        Err(message) => {
            eprintln!("error: {message}");
            return ExitCode::from(2);
        }
    };
    for notice in &config.notices {
        eprintln!("notice: {notice}");
    }
    if config.api_url.starts_with("http://") {
        eprintln!(
            "WARNING: plain HTTP: the key and the readings are not encrypted. Bench use only."
        );
    }
    let (mut spool, dropped) = match Spool::open(&config.spool, config.limits, now_secs()) {
        Ok(opened) => opened,
        Err(error) => {
            eprintln!("error: cannot open spool {}: {error}", config.spool);
            return ExitCode::FAILURE;
        }
    };
    if dropped > 0 {
        eprintln!("spool: dropped {dropped} readings over the size or age cap");
    }
    let mut stamper = match Stamper::open(format!("{}.boot", config.spool), now_secs()) {
        Ok(stamper) => stamper,
        Err(error) => {
            eprintln!("error: cannot keep the boot counter beside the spool: {error}");
            return ExitCode::FAILURE;
        }
    };
    eprintln!("gateway boot {}", stamper.boot());
    let mut sender = http::UreqSender::new(&config.api_url, config.api_key.clone());

    // a thread reads input and the loop spools it. A forwarding pass is cut short after a couple
    // of seconds and the loop then comes back to the queue, so a slow server never leaves input
    // unread (an unread pipe fills and a serial bridge behind it loses bytes)
    let (tx, rx) = mpsc::sync_channel::<Line>(QUEUE_LINES);
    let max_line = config.max_line_bytes;
    spawn_reader(tx, max_line);

    let mut waits = Waits::default();
    let mut totals = Totals::default();
    let mut input_done = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(1)) {
            Ok(Line::Eof) | Err(mpsc::RecvTimeoutError::Disconnected) => input_done = true,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Ok(line) => {
                if let Err(code) = take(line, max_line, &mut stamper, &mut spool) {
                    return code;
                }
            }
        }
        // anything already waiting is taken before a pass starts
        while let Ok(line) = rx.try_recv() {
            if let Err(code) = take(line, max_line, &mut stamper, &mut spool) {
                return code;
            }
        }
        if !spool.is_empty() && Instant::now() >= waits.retry_at {
            match flush(&mut spool, &mut sender, now_secs(), PASS_BUDGET) {
                Ok(done) => {
                    if done.stale > 0 {
                        eprintln!(
                            "{} readings were already known to the API (409)",
                            done.stale
                        );
                    }
                    if done.dropped > 0 {
                        eprintln!("spool: dropped {} readings over the age cap", done.dropped);
                    }
                    totals.add(&done);
                    waits.after(&done.stop);
                    waits.last = Some((done.stop, done.last_status));
                }
                Err(error) => eprintln!("error: spool unreadable: {error}"),
            }
        }
        if input_done && (spool.is_empty() || Instant::now() < waits.retry_at) {
            break;
        }
    }
    let left = spool.len();
    eprintln!(
        "phaemos-edge: forwarded {}, already known to the API {}, set aside as bad {}, dropped over a cap {}, left in the spool {left}. Of those forwarded, {} went in as backlog (stored at their own time)",
        totals.sent, totals.stale, totals.rejected, totals.dropped, totals.backlog
    );
    ExitCode::from(exit_for(left, waits.last.as_ref()))
}

#[derive(Default)]
struct Totals {
    sent: usize,
    stale: usize,
    rejected: usize,
    dropped: usize,
    backlog: usize,
}

impl Totals {
    fn add(&mut self, done: &Flushed) {
        self.sent += done.sent;
        self.stale += done.stale;
        self.rejected += done.rejected;
        self.dropped += done.dropped;
        self.backlog += done.backlog;
    }
}

/// the exit code at the end of input. Readings left behind are never a quiet 0: the code says why, with
/// the same meanings phaemosctl uses (3 the key was refused, 6 refused or conflicting, 7 rate limited,
/// 8 the server or the network failed).
fn exit_for(left: usize, last: Option<&(Stop, Option<u16>)>) -> u8 {
    if left == 0 {
        return 0;
    }
    match last {
        Some((Stop::AuthRefused, _)) => 3,
        Some((Stop::CounterRefused | Stop::TooManyRejected | Stop::AddressWrong, _)) => 6,
        Some((_, Some(429))) => 7,
        _ => 8,
    }
}

/// reads standard input on its own thread and sends each line to the loop.
fn spawn_reader(tx: mpsc::SyncSender<Line>, max_line: usize) {
    thread::spawn(move || {
        let mut input = BufReader::new(io::stdin().lock());
        loop {
            match read_line(&mut input, max_line) {
                Ok(Line::Eof) | Err(_) => break,
                Ok(line) => {
                    if tx.send(line).is_err() {
                        break;
                    }
                }
            }
        }
    });
}

/// when the next forwarding pass may start, with how many passes in a row have failed.
struct Waits {
    failures: u32,
    auth_failures: u32,
    retry_at: Instant,
    /// how the last pass ended and the status that ended it.
    last: Option<(Stop, Option<u16>)>,
    /// the wrong-address fault is reported once, not on every pass.
    reported_address: bool,
}

impl Default for Waits {
    fn default() -> Self {
        Self {
            failures: 0,
            auth_failures: 0,
            retry_at: Instant::now(),
            last: None,
            reported_address: false,
        }
    }
}

impl Waits {
    fn after(&mut self, stop: &Stop) {
        match stop {
            Stop::Empty | Stop::Yield => {
                self.failures = 0;
                self.auth_failures = 0;
            }
            Stop::Retry(wait) => {
                self.failures = self.failures.saturating_add(1);
                self.auth_failures = 0;
                // never retry sooner than the API asked
                let delay = wait.map_or(backoff::delay(self.failures), |w| {
                    w.max(backoff::delay(self.failures))
                });
                self.retry_at = Instant::now() + delay;
            }
            Stop::TooManyRejected => {
                self.failures = self.failures.saturating_add(1);
                self.retry_at = Instant::now() + backoff::delay(self.failures);
            }
            Stop::AddressWrong => {
                if !self.reported_address {
                    self.reported_address = true;
                    eprintln!("the API answered 404 for the telemetry route: --url is wrong. It must be the base address only, with no path and no trailing slash. The readings are kept and the gateway will try again after a long wait");
                }
                self.auth_failures = self.auth_failures.saturating_add(1);
                self.retry_at = Instant::now() + backoff::auth_delay(self.auth_failures);
            }
            Stop::AuthRefused | Stop::CounterRefused => {
                self.auth_failures = self.auth_failures.saturating_add(1);
                self.retry_at = Instant::now() + backoff::auth_delay(self.auth_failures);
            }
        }
    }
}

fn take(
    line: Line,
    max_line: usize,
    stamper: &mut Stamper,
    spool: &mut Spool,
) -> Result<(), ExitCode> {
    match line {
        Line::Text(text) if !text.trim().is_empty() => accept(&text, stamper, spool),
        Line::TooLong(length) => {
            eprintln!("skipped a line of {length} bytes: over the {max_line} byte cap");
            Ok(())
        }
        _ => Ok(()),
    }
}

/// checks a line, stamps it with the gateway's pair and spools it. Returns the exit code when the
/// spool cannot be written.
fn accept(text: &str, stamper: &mut Stamper, spool: &mut Spool) -> Result<(), ExitCode> {
    if let Err(problem) = reading::parse_line(text) {
        eprintln!("skipped a line: {problem}");
        return Ok(());
    }
    let ready = match stamper.stamp(text.trim(), now_secs()) {
        Ok(line) => line,
        Err(problem) => {
            eprintln!("error: cannot stamp reading: {problem}");
            return Err(ExitCode::FAILURE);
        }
    };
    match spool.push(&ready, now_secs()) {
        Ok(0) => Ok(()),
        Ok(dropped) => {
            eprintln!("spool: dropped {dropped} oldest readings over the size or age cap");
            Ok(())
        }
        Err(error) => {
            eprintln!("error: cannot spool reading: {error}");
            Err(ExitCode::FAILURE)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::exit_for;
    use phaemos_edge::forward::Stop;

    #[test]
    fn nothing_left_is_a_quiet_zero_and_anything_left_says_why() {
        assert_eq!(exit_for(0, None), 0);
        assert_eq!(exit_for(0, Some(&(Stop::AuthRefused, Some(401)))), 0);
        assert_eq!(exit_for(3, Some(&(Stop::AuthRefused, Some(401)))), 3);
        assert_eq!(exit_for(3, Some(&(Stop::CounterRefused, Some(409)))), 6);
        assert_eq!(exit_for(3, Some(&(Stop::AddressWrong, Some(404)))), 6);
        assert_eq!(exit_for(3, Some(&(Stop::TooManyRejected, Some(422)))), 6);
        assert_eq!(exit_for(3, Some(&(Stop::Retry(None), Some(429)))), 7);
        assert_eq!(exit_for(3, Some(&(Stop::Retry(None), Some(503)))), 8);
        assert_eq!(exit_for(3, Some(&(Stop::Retry(None), None))), 8);
        assert_eq!(exit_for(3, None), 8);
    }

    #[test]
    fn a_wrong_address_is_reported_once_and_waited_out_for_a_long_time() {
        use super::Waits;
        use std::time::{Duration, Instant};
        let mut waits = Waits::default();
        waits.after(&Stop::AddressWrong);
        assert!(waits.reported_address);
        assert!(
            waits.retry_at > Instant::now() + Duration::from_secs(290),
            "a 404 must not be retried every few seconds"
        );
        let first = waits.retry_at;
        waits.after(&Stop::AddressWrong);
        assert!(waits.retry_at > first, "the wait grows");
        waits.after(&Stop::Empty);
        assert_eq!(waits.auth_failures, 0);
    }
}
