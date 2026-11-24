//! forwards spooled readings in order and decides what each reply means.

use std::io;
use std::time::{Duration, Instant};

use crate::outcome::{classify, Outcome};
use crate::spool::Spool;

/// the cursor is saved after this many readings, not after each one.
const COMMIT_EVERY: usize = 50;
/// this many readings in a row refused as bad stop the pass: something other than one bad reading is
/// wrong (a proxy, a changed API) and the rest of the spool is kept.
const REJECTED_RUN_LIMIT: usize = 3;
/// this many 409 answers in a row stop the pass. After a crash up to `COMMIT_EVERY` readings
/// that were already accepted are sent again and answered 409, so the limit is above that: a longer
/// run means the counter itself is behind (a wiped state folder, a clock set back) and the rest of
/// the spool is kept until an admin accepts a new counter.
const STALE_RUN_LIMIT: usize = 2 * COMMIT_EVERY;

#[derive(Debug)]
pub struct Reply {
    pub status: u16,
    pub retry_after: Option<String>,
}

/// the answer to a batch post: the status of the whole request and, when it was accepted, one status
/// for each reading in the order sent.
#[derive(Debug)]
pub struct BatchReply {
    pub status: u16,
    pub retry_after: Option<String>,
    pub items: Vec<ItemResult>,
}

/// the answer for one reading of a batch: the status a single post of it would have had, the API's stable
/// `code` for a refusal and whether a stored reading went in as backlog (never judged as live).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemResult {
    pub status: u16,
    pub code: Option<String>,
    pub backlog: bool,
}

impl ItemResult {
    #[must_use]
    pub fn new(status: u16) -> Self {
        Self {
            status,
            code: None,
            backlog: false,
        }
    }
}

/// the most readings sent in one batch post.
pub const BATCH_MAX: usize = 100;

/// sends readings to the API. A transport failure (no network, a time-out) is an `Err`.
pub trait Sender {
    /// sends one reading's JSON.
    ///
    /// # Errors
    ///
    /// returns a description (never holding the key) when no reply came back.
    fn send(&mut self, body: &str) -> Result<Reply, String>;

    /// sends up to `BATCH_MAX` readings in one post. `Ok(None)` means this server has no batch route
    /// (or the sender has learned that it has none), so the caller sends the readings one at a time.
    ///
    /// # Errors
    ///
    /// returns a description (never holding the key) when no reply came back.
    fn send_batch(&mut self, _bodies: &[String]) -> Result<Option<BatchReply>, String> {
        Ok(None)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum Stop {
    /// the spool is empty.
    Empty,
    /// the time budget for this pass ran out with readings still queued. Not a failure: go back to
    /// reading input and carry on later.
    Yield,
    /// try again later, after the wait the API named if it named one.
    Retry(Option<Duration>),
    /// the key was refused: wait a long time and keep the spool.
    AuthRefused,
    /// three readings in a row were refused as bad: wait and keep the rest.
    TooManyRejected,
    /// the API answered 404: the address is wrong. Reported once by the caller and waited out for a long time.
    AddressWrong,
    /// a long run of 409 answers: the counter is behind. Wait a long time and keep the rest.
    CounterRefused,
}

#[derive(Debug, PartialEq, Eq)]
pub struct Flushed {
    pub sent: usize,
    pub rejected: usize,
    /// answered 409: the API already has this reading or something newer.
    pub stale: usize,
    pub dropped: usize,
    /// readings the API stored as backlog (taken at their own time and never judged as live).
    pub backlog: usize,
    pub stop: Stop,
    /// the status that ended the pass, when a reply did (a 429 says "rate limited", a 5xx says "failed").
    pub last_status: Option<u16>,
}

struct Pass<'a> {
    spool: &'a mut Spool,
    now: u64,
    sent: usize,
    rejected: usize,
    stale: usize,
    backlog: usize,
    rejected_run: usize,
    stale_run: usize,
    since_commit: usize,
}

impl Pass<'_> {
    /// applies what one reading's answer means. Returns the reason to stop, if there is one.
    fn apply(
        &mut self,
        status: u16,
        retry_after: Option<&str>,
        code: Option<&str>,
    ) -> io::Result<Option<Stop>> {
        let stop = match classify(status, retry_after) {
            Outcome::Sent => {
                self.spool.pop_front();
                self.sent += 1;
                self.rejected_run = 0;
                self.stale_run = 0;
                None
            }
            Outcome::Stale => {
                self.spool.pop_front();
                self.stale += 1;
                self.stale_run += 1;
                self.rejected_run = 0;
                if self.stale_run >= STALE_RUN_LIMIT {
                    eprintln!(
                        "the API answered 409 {} times in a row: its counter for this gateway is ahead. Keeping {} spooled. Check the state folder was not wiped or the clock set back, then ask an admin to accept a new counter (phaemosctl devices accept-counter)",
                        self.stale_run,
                        self.spool.len()
                    );
                    Some(Stop::CounterRefused)
                } else {
                    None
                }
            }
            Outcome::Permanent => {
                eprintln!("the API refused a reading as bad (status {status}): moved to the rejected file");
                self.spool.reject(status, code.unwrap_or("-"), self.now)?;
                self.rejected += 1;
                self.rejected_run += 1;
                self.stale_run = 0;
                if self.rejected_run >= REJECTED_RUN_LIMIT {
                    eprintln!(
                        "{REJECTED_RUN_LIMIT} readings in a row were refused as bad: stopping this pass and keeping {} spooled. Check the API address and version",
                        self.spool.len()
                    );
                    Some(Stop::TooManyRejected)
                } else {
                    None
                }
            }
            Outcome::NotFound => Some(Stop::AddressWrong),
            Outcome::Auth => {
                eprintln!(
                    "the API refused the key (status {status}): keeping {} spooled and waiting",
                    self.spool.len()
                );
                Some(Stop::AuthRefused)
            }
            Outcome::Retry(wait) => {
                if (300..400).contains(&status) {
                    eprintln!(
                        "the API answered with a redirect (status {status}) and redirects are not followed, so the key is never sent to another address. The address is probably wrong or http:// where https:// is needed. Check --url. Keeping {} spooled",
                        self.spool.len()
                    );
                } else {
                    eprintln!(
                        "the API said try later (status {status}): keeping {} spooled",
                        self.spool.len()
                    );
                }
                Some(Stop::Retry(wait))
            }
        };
        if stop.is_none() {
            self.since_commit += 1;
            if self.since_commit >= COMMIT_EVERY {
                self.spool.commit()?;
                self.since_commit = 0;
            }
        }
        Ok(stop)
    }
}

/// sends pending readings oldest first for at most `budget`, so the caller can go back to reading
/// input. Readings go in batches when the server has a batch route and one at a time when it has not
/// (or when a whole batch is refused, so a bad reading is found and set aside on its own). A reading the
/// API says is bad is moved to the rejected file and the pass carries on, up to three in a row. Any other
/// failure stops the pass with the reading still queued.
///
/// # Errors
///
/// returns an error from the spool files.
#[allow(clippy::too_many_lines)]
pub fn flush<S: Sender>(
    spool: &mut Spool,
    sender: &mut S,
    now: u64,
    budget: Duration,
) -> io::Result<Flushed> {
    let started = Instant::now();
    let dropped = spool.expire(now);
    let mut pass = Pass {
        spool,
        now,
        sent: 0,
        rejected: 0,
        stale: 0,
        backlog: 0,
        rejected_run: 0,
        stale_run: 0,
        since_commit: 0,
    };
    let mut single_only = false;
    let mut last_status = None;
    let stop = 'pass: loop {
        if pass.spool.is_empty() {
            break Stop::Empty;
        }
        if started.elapsed() >= budget {
            break Stop::Yield;
        }
        if !single_only {
            let bodies = pass.spool.front_lines(BATCH_MAX);
            match sender.send_batch(&bodies) {
                Err(error) => {
                    eprintln!(
                        "forward failed, keeping {} spooled: {error}",
                        pass.spool.len()
                    );
                    break Stop::Retry(None);
                }
                Ok(None) => single_only = true,
                Ok(Some(reply)) => {
                    last_status = Some(reply.status);
                    if (200..300).contains(&reply.status) {
                        if reply.items.len() != bodies.len() {
                            eprintln!(
                                "the batch answer held {} results for {} readings: keeping them spooled",
                                reply.items.len(),
                                bodies.len()
                            );
                            break Stop::Retry(None);
                        }
                        for item in reply.items {
                            last_status = Some(item.status);
                            if !matches!(item.status, 200 | 201 | 409 | 422) {
                                // anything else for one reading (a 5xx, an odd status) is not judged here:
                                // that reading and the ones behind it stay queued and the next pass sends
                                // the front reading alone
                                single_only = true;
                                continue 'pass;
                            }
                            if item.status == 201 && item.backlog {
                                pass.backlog += 1;
                            }
                            if let Some(stop) =
                                pass.apply(item.status, None, item.code.as_deref())?
                            {
                                break 'pass stop;
                            }
                        }
                        continue;
                    }
                    match classify(reply.status, reply.retry_after.as_deref()) {
                        // the whole batch was refused as bad or stale: find the cause one reading at a time
                        Outcome::Permanent | Outcome::Stale => single_only = true,
                        _ => {
                            if let Some(stop) =
                                pass.apply(reply.status, reply.retry_after.as_deref(), None)?
                            {
                                break stop;
                            }
                        }
                    }
                    continue;
                }
            }
        }
        let Some(front) = pass.spool.front() else {
            break Stop::Empty;
        };
        let body = front.line.clone();
        let reply = match sender.send(&body) {
            Ok(reply) => reply,
            Err(error) => {
                eprintln!(
                    "forward failed, keeping {} spooled: {error}",
                    pass.spool.len()
                );
                break Stop::Retry(None);
            }
        };
        last_status = Some(reply.status);
        if let Some(stop) = pass.apply(reply.status, reply.retry_after.as_deref(), None)? {
            break stop;
        }
    };
    let (sent, rejected, stale, backlog) = (pass.sent, pass.rejected, pass.stale, pass.backlog);
    spool.commit()?;
    let last_status = if stop == Stop::Empty || stop == Stop::Yield {
        None
    } else {
        last_status
    };
    Ok(Flushed {
        sent,
        rejected,
        stale,
        dropped,
        backlog,
        stop,
        last_status,
    })
}

#[cfg(test)]
mod tests {
    use super::{flush, BatchReply, ItemResult, Reply, Sender, Stop};
    use crate::spool::{Limits, Spool};
    use std::collections::VecDeque;
    use std::time::Duration;

    struct Fake {
        replies: VecDeque<Result<Reply, String>>,
        seen: Vec<String>,
    }

    impl Sender for Fake {
        fn send(&mut self, body: &str) -> Result<Reply, String> {
            self.seen.push(body.to_string());
            self.replies.pop_front().unwrap_or(Ok(Reply {
                status: 201,
                retry_after: None,
            }))
        }
    }

    #[allow(clippy::unnecessary_wraps)]
    fn reply(status: u16, retry_after: Option<&str>) -> Result<Reply, String> {
        Ok(Reply {
            status,
            retry_after: retry_after.map(str::to_string),
        })
    }

    fn fake(replies: Vec<Result<Reply, String>>) -> Fake {
        Fake {
            replies: replies.into(),
            seen: Vec::new(),
        }
    }

    fn spool_with(name: &str, ids: &[&str]) -> (Spool, std::path::PathBuf) {
        let dir =
            std::env::temp_dir().join(format!("phaemos-edge-fwd-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let path = dir.join("spool.jsonl");
        let (mut spool, _) = Spool::open(&path, Limits::default(), 100).unwrap();
        for id in ids {
            spool
                .push(&format!(r#"{{"device_id":"{id}"}}"#), 100)
                .unwrap();
        }
        (spool, path)
    }

    const BUDGET: Duration = Duration::from_secs(60);

    #[test]
    fn sends_everything_in_order() {
        let (mut spool, _) = spool_with("all", &["a", "b", "c"]);
        let mut sender = fake(vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(
            (out.sent, out.rejected, out.stale, out.dropped, out.stop),
            (3, 0, 0, 0, Stop::Empty)
        );
        assert!(spool.is_empty());
        assert_eq!(sender.seen.len(), 3);
        assert!(sender.seen[0].contains('a'));
    }

    #[test]
    fn a_reading_the_api_calls_bad_does_not_block_the_ones_behind_it() {
        let (mut spool, path) = spool_with("perm", &["bad", "good1", "good2"]);
        let mut sender = fake(vec![reply(422, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.sent, out.rejected, out.stop), (2, 1, Stop::Empty));
        let rejected = std::fs::read_to_string(format!("{}.rejected", path.display())).unwrap();
        assert!(rejected.starts_with("200\t422\t-\t100\t"));
        assert!(rejected.contains("bad"));
    }

    #[test]
    fn a_404_from_whatever_answers_empties_nothing() {
        let ids: Vec<String> = (0..200).map(|i| format!("n{i}")).collect();
        let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
        let (mut spool, path) = spool_with("404", &refs);
        let mut sender = fake(vec![reply(404, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.rejected, out.stop), (0, Stop::AddressWrong));
        assert_eq!(spool.len(), 200);
        assert_eq!(sender.seen.len(), 1);
        assert!(!std::path::Path::new(&format!("{}.rejected", path.display())).exists());
    }

    #[test]
    fn three_bad_readings_in_a_row_stop_the_pass_and_keep_the_rest() {
        let ids: Vec<String> = (0..20).map(|i| format!("n{i}")).collect();
        let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
        let (mut spool, _) = spool_with("run", &refs);
        let mut sender = fake(vec![reply(400, None), reply(400, None), reply(400, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(
            (out.rejected, out.sent, out.stop),
            (3, 0, Stop::TooManyRejected)
        );
        assert_eq!(spool.len(), 17);
    }

    #[test]
    fn bad_readings_that_are_not_in_a_row_do_not_stop_the_pass() {
        let (mut spool, _) = spool_with("apart", &["a", "b", "c", "d", "e"]);
        let mut sender = fake(vec![
            reply(400, None),
            reply(400, None),
            reply(201, None),
            reply(400, None),
            reply(400, None),
        ]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.rejected, out.sent, out.stop), (4, 1, Stop::Empty));
    }

    #[test]
    fn a_conflict_counts_as_stale_and_never_as_rejected() {
        let (mut spool, path) = spool_with("409", &["a", "b", "c"]);
        let mut sender = fake(vec![reply(409, None), reply(409, None), reply(201, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(
            (out.stale, out.rejected, out.sent, out.stop),
            (2, 0, 1, Stop::Empty)
        );
        assert!(!std::path::Path::new(&format!("{}.rejected", path.display())).exists());
    }

    #[test]
    fn a_long_run_of_conflicts_keeps_the_rest_of_the_spool() {
        let ids: Vec<String> = (0..300).map(|i| format!("n{i}")).collect();
        let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
        let (mut spool, _) = spool_with("409run", &refs);
        let replies = (0..300).map(|_| reply(409, None)).collect();
        let mut sender = fake(replies);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(out.stop, Stop::CounterRefused);
        assert_eq!(out.stale, 100);
        assert_eq!(spool.len(), 200);
    }

    #[test]
    fn rate_limit_keeps_the_spool_and_reports_the_wait() {
        let (mut spool, _) = spool_with("429", &["a", "b"]);
        let mut sender = fake(vec![reply(429, Some("45"))]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(out.stop, Stop::Retry(Some(Duration::from_secs(45))));
        assert_eq!(spool.len(), 2);
        assert_eq!(sender.seen.len(), 1);
    }

    #[test]
    fn wrong_key_keeps_everything_and_rejects_nothing() {
        let (mut spool, path) = spool_with("401", &["a", "b"]);
        let mut sender = fake(vec![reply(401, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.rejected, out.stop), (0, Stop::AuthRefused));
        assert_eq!(spool.len(), 2);
        assert!(!std::path::Path::new(&format!("{}.rejected", path.display())).exists());
    }

    #[test]
    fn a_redirect_blocks_nothing_for_ever_and_keeps_the_spool() {
        let (mut spool, _) = spool_with("307", &["a", "b"]);
        let mut sender = fake(vec![reply(307, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(out.stop, Stop::Retry(None));
        assert_eq!(spool.len(), 2);
    }

    #[test]
    fn server_error_and_network_failure_retry() {
        let (mut spool, _) = spool_with("5xx", &["a", "b"]);
        let mut sender = fake(vec![reply(201, None), reply(503, None)]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.sent, out.stop), (1, Stop::Retry(None)));
        assert_eq!(spool.len(), 1);
        let mut sender = fake(vec![Err("time-out".to_string())]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(out.stop, Stop::Retry(None));
        assert_eq!(spool.len(), 1);
    }

    #[test]
    fn a_pass_yields_when_its_budget_runs_out() {
        let ids: Vec<String> = (0..10).map(|i| format!("n{i}")).collect();
        let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
        let (mut spool, _) = spool_with("budget", &refs);
        let mut sender = fake(vec![]);
        // a zero budget allows no send at all: the caller gets control straight back
        let out = flush(&mut spool, &mut sender, 200, Duration::ZERO).unwrap();
        assert_eq!((out.sent, out.stop), (0, Stop::Yield));
        assert_eq!(spool.len(), 10);
    }

    #[test]
    fn a_slow_server_cannot_hold_a_pass_past_its_budget() {
        struct Slow(usize);
        impl Sender for Slow {
            fn send(&mut self, _: &str) -> Result<Reply, String> {
                self.0 += 1;
                std::thread::sleep(Duration::from_millis(60));
                Ok(Reply {
                    status: 201,
                    retry_after: None,
                })
            }
        }
        let ids: Vec<String> = (0..50).map(|i| format!("n{i}")).collect();
        let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
        let (mut spool, _) = spool_with("slow", &refs);
        let mut sender = Slow(0);
        let began = std::time::Instant::now();
        let out = flush(&mut spool, &mut sender, 200, Duration::from_millis(200)).unwrap();
        assert_eq!(out.stop, Stop::Yield);
        assert!(sender.0 < 40, "{} sends in a 200 ms budget", sender.0);
        assert!(began.elapsed() < Duration::from_secs(3));
        assert_eq!(spool.len(), 50 - sender.0);
    }

    #[test]
    fn progress_survives_a_restart() {
        let (mut spool, path) = spool_with("restart", &["a", "b", "c"]);
        let mut sender = fake(vec![reply(201, None), reply(500, None)]);
        flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        drop(spool);
        let (spool, _) = Spool::open(&path, Limits::default(), 200).unwrap();
        assert_eq!(spool.len(), 2);
    }

    #[test]
    fn old_readings_are_dropped_and_counted() {
        let (spool, path) = spool_with("age", &["a", "b"]);
        drop(spool);
        let limits = Limits {
            max_bytes: 1 << 20,
            max_age_secs: 10,
        };
        let (mut spool, _) = Spool::open(&path, limits, 100).unwrap();
        let mut sender = fake(vec![]);
        let out = flush(&mut spool, &mut sender, 500, BUDGET).unwrap();
        assert_eq!((out.dropped, out.sent, out.stop), (2, 0, Stop::Empty));
    }

    // ---- the batch route (not yet on the server: these follow the assumed shape) ----

    struct Batching {
        batches: VecDeque<Result<Option<BatchReply>, String>>,
        singles: VecDeque<Result<Reply, String>>,
        batch_sizes: Vec<usize>,
        single_calls: usize,
    }

    impl Sender for Batching {
        fn send(&mut self, _body: &str) -> Result<Reply, String> {
            self.single_calls += 1;
            self.singles.pop_front().unwrap_or(Ok(Reply {
                status: 201,
                retry_after: None,
            }))
        }

        fn send_batch(&mut self, bodies: &[String]) -> Result<Option<BatchReply>, String> {
            self.batch_sizes.push(bodies.len());
            self.batches.pop_front().unwrap_or(Ok(None))
        }
    }

    fn batching(
        batches: Vec<Result<Option<BatchReply>, String>>,
        singles: Vec<Result<Reply, String>>,
    ) -> Batching {
        Batching {
            batches: batches.into(),
            singles: singles.into(),
            batch_sizes: Vec::new(),
            single_calls: 0,
        }
    }

    #[allow(clippy::unnecessary_wraps)]
    fn all_ok(n: usize) -> Result<Option<BatchReply>, String> {
        Ok(Some(BatchReply {
            status: 200,
            retry_after: None,
            items: vec![ItemResult::new(201); n],
        }))
    }

    fn ids(n: usize) -> Vec<String> {
        (0..n).map(|i| format!("n{i}")).collect()
    }

    #[test]
    fn a_backlog_drains_in_batches_of_at_most_a_hundred() {
        let names = ids(250);
        let refs: Vec<&str> = names.iter().map(String::as_str).collect();
        let (mut spool, _) = spool_with("batch250", &refs);
        let mut sender = batching(vec![all_ok(100), all_ok(100), all_ok(50)], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.sent, out.stop), (250, Stop::Empty));
        assert_eq!(sender.batch_sizes, vec![100, 100, 50]);
        assert_eq!(sender.single_calls, 0);
    }

    #[test]
    fn a_server_with_no_batch_route_falls_back_to_single_posts() {
        let (mut spool, _) = spool_with("nobatch", &["a", "b", "c"]);
        let mut sender = batching(vec![Ok(None)], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.sent, out.stop), (3, Stop::Empty));
        assert_eq!(sender.single_calls, 3);
        assert_eq!(
            sender.batch_sizes.len(),
            1,
            "the batch route is tried once and then left alone"
        );
    }

    #[test]
    fn each_reading_in_a_batch_is_judged_on_its_own_status() {
        let (mut spool, path) = spool_with("mixed", &["ok", "bad", "dup", "later", "after"]);
        let mut results: Vec<ItemResult> = [201, 422, 409, 503, 201]
            .into_iter()
            .map(ItemResult::new)
            .collect();
        results[0].backlog = true;
        results[1].code = Some("observed_at_too_old".to_string());
        let reply = BatchReply {
            status: 200,
            retry_after: None,
            items: results,
        };
        // the reading with the odd status (503) is then sent alone and the server is still busy
        let mut sender = batching(
            vec![Ok(Some(reply))],
            vec![Ok(Reply {
                status: 503,
                retry_after: None,
            })],
        );
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(
            (out.sent, out.rejected, out.stale, out.backlog, out.stop),
            (1, 1, 1, 1, Stop::Retry(None))
        );
        assert_eq!(out.last_status, Some(503));
        assert_eq!(sender.single_calls, 1);
        assert_eq!(spool.len(), 2);
        assert!(spool.lines()[0].contains("later") && spool.lines()[1].contains("after"));
        // a 422 goes to the rejected file with the API's code
        let rejected = std::fs::read_to_string(format!("{}.rejected", path.display())).unwrap();
        assert!(rejected.contains("\t422\tobserved_at_too_old\t") && rejected.contains("bad"));
    }

    #[test]
    fn a_batch_refused_as_a_whole_is_retried_one_reading_at_a_time() {
        let (mut spool, _) = spool_with("wholebad", &["a", "bad", "c"]);
        let refused = Ok(Some(BatchReply {
            status: 422,
            retry_after: None,
            items: vec![],
        }));
        let mut sender = batching(
            vec![refused],
            vec![
                Ok(Reply {
                    status: 201,
                    retry_after: None,
                }),
                Ok(Reply {
                    status: 422,
                    retry_after: None,
                }),
            ],
        );
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.sent, out.rejected, out.stop), (2, 1, Stop::Empty));
        assert_eq!(sender.single_calls, 3);
    }

    #[test]
    fn batch_level_429_and_key_refusals_stop_the_pass_and_keep_everything() {
        let (mut spool, _) = spool_with("batch429", &["a", "b"]);
        let limited = Ok(Some(BatchReply {
            status: 429,
            retry_after: Some("30".to_string()),
            items: vec![],
        }));
        let mut sender = batching(vec![limited], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(out.stop, Stop::Retry(Some(Duration::from_secs(30))));
        assert_eq!((out.last_status, spool.len()), (Some(429), 2));
        let denied = Ok(Some(BatchReply {
            status: 401,
            retry_after: None,
            items: vec![],
        }));
        let mut sender = batching(vec![denied], vec![]);
        assert_eq!(
            flush(&mut spool, &mut sender, 200, BUDGET).unwrap().stop,
            Stop::AuthRefused
        );
        assert_eq!(spool.len(), 2);
    }

    #[test]
    fn a_batch_answer_with_the_wrong_number_of_results_keeps_the_readings() {
        let (mut spool, _) = spool_with("short", &["a", "b", "c"]);
        let mut sender = batching(vec![all_ok(2)], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.stop, spool.len()), (Stop::Retry(None), 3));
    }

    #[test]
    fn a_transport_failure_on_a_batch_keeps_the_readings() {
        let (mut spool, _) = spool_with("batchnet", &["a", "b"]);
        let mut sender = batching(vec![Err("time-out".to_string())], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!((out.stop, spool.len()), (Stop::Retry(None), 2));
    }

    #[test]
    fn all_stale_results_in_a_batch_are_counted_as_stale_and_not_rejected() {
        let (mut spool, path) = spool_with("batchstale", &["a", "b", "c"]);
        let reply = BatchReply {
            status: 200,
            retry_after: None,
            items: [200, 409, 409].into_iter().map(ItemResult::new).collect(),
        };
        let mut sender = batching(vec![Ok(Some(reply))], vec![]);
        let out = flush(&mut spool, &mut sender, 200, BUDGET).unwrap();
        assert_eq!(
            (out.sent, out.stale, out.rejected, out.stop),
            (1, 2, 0, Stop::Empty)
        );
        assert!(!std::path::Path::new(&format!("{}.rejected", path.display())).exists());
    }
}
