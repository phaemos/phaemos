//! `phaemos-edge`: reads readings as JSON lines on stdin (for example from a node's
//! serial bridge), spools them to disk and forwards them to the PHAEMOS API.
//!
//! usage: `phaemos-edge --api-url https://api.phaemos.com --api-key KEY [--spool PATH]`

use std::io::{self, BufRead};
use std::process::ExitCode;
use std::time::Instant;

use phaemos_edge::{backoff, reading, spool::Spool};

struct Config {
    api_url: String,
    api_key: String,
    spool: String,
}

fn parse_args() -> Result<Config, String> {
    let mut api_url = None;
    let mut api_key = std::env::var("PHAEMOS_API_KEY").ok();
    let mut spool = "phaemos-spool.jsonl".to_string();
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        let value = args.next().ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--api-url" => api_url = Some(value.trim_end_matches('/').to_string()),
            "--api-key" => api_key = Some(value),
            "--spool" => spool = value,
            other => return Err(format!("unknown flag {other}")),
        }
    }
    Ok(Config {
        api_url: api_url.ok_or("--api-url is required")?,
        api_key: api_key.ok_or("--api-key or PHAEMOS_API_KEY is required")?,
        spool,
    })
}

/// sends pending readings in order and stops at the first failure, so the spool
/// keeps its order. Returns how many were forwarded.
fn flush(config: &Config, spool: &Spool) -> io::Result<(usize, bool)> {
    let url = format!("{}/api/v1/telemetry", config.api_url);
    let mut sent = 0;
    let mut failed = false;
    for line in spool.pending()? {
        let result = ureq::post(&url)
            .header("X-API-Key", &config.api_key)
            .header("Content-Type", "application/json")
            .send(line.as_str());
        if let Err(error) = result {
            eprintln!(
                "forward failed, keeping {} spooled: {error}",
                spool.pending()?.len() - sent
            );
            failed = true;
            break;
        }
        sent += 1;
    }
    spool.ack(sent)?;
    Ok((sent, failed))
}

fn main() -> ExitCode {
    let config = match parse_args() {
        Ok(config) => config,
        Err(message) => {
            eprintln!("error: {message}");
            return ExitCode::from(2);
        }
    };
    let spool = match Spool::open(&config.spool) {
        Ok(spool) => spool,
        Err(error) => {
            eprintln!("error: cannot open spool {}: {error}", config.spool);
            return ExitCode::FAILURE;
        }
    };

    let mut attempt = 0;
    let mut retry_at = Instant::now();
    for line in io::stdin().lock().lines() {
        let Ok(line) = line else { break };
        match reading::parse_line(&line) {
            Ok(_) => {
                if let Err(error) = spool.push(&line) {
                    eprintln!("error: cannot spool reading: {error}");
                    return ExitCode::FAILURE;
                }
            }
            Err(problem) => {
                eprintln!("skipped a line: {problem}");
                continue;
            }
        }
        if Instant::now() < retry_at {
            continue;
        }
        match flush(&config, &spool) {
            Ok((_, false)) => attempt = 0,
            Ok((_, true)) => {
                attempt += 1;
                retry_at = Instant::now() + backoff::delay(attempt);
            }
            Err(error) => eprintln!("error: spool unreadable: {error}"),
        }
    }
    ExitCode::SUCCESS
}
