//! what a reply from the API means for the reading that was sent.

use std::time::Duration;

/// the longest `Retry-After` the gateway will obey, so one odd header cannot park it for days.
const RETRY_AFTER_MAX_SECS: u64 = 3600;
/// used when the API says to slow down (429) without a usable `Retry-After`.
const RATE_LIMIT_DEFAULT_SECS: u64 = 60;

#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    /// the API stored the reading.
    Sent,
    /// the API says the reading itself is bad (400, 413 or 422): move it to the rejected file and
    /// carry on, so one bad line cannot block the rest. Any other 4xx is about the request or the
    /// address (a 404 from a wrong path, a 405, a 415 from a proxy) and says nothing about the
    /// reading, so it is retried and nothing is thrown away.
    Permanent,
    /// the route was not found (404): the address is wrong (a path or a trailing slash the server does not
    /// accept). Nothing is rejected, because every reading would get the same answer. The spool is kept, the
    /// fault is reported once and the gateway waits a long time.
    NotFound,
    /// the API already has this reading or something newer (409): the counter of this post is not
    /// newer than the last one accepted. Counted on its own. It is not rejected data.
    Stale,
    /// the key was refused. A wrong key will not fix itself and every spooled reading would be
    /// refused too, so nothing is rejected: the spool is kept and the gateway waits a long time.
    Auth,
    /// try again later, after the given wait if the API named one.
    Retry(Option<Duration>),
}

/// reads the whole-seconds form of `Retry-After`. The date form is not read, because it needs
/// the clocks to agree, so it counts as absent.
#[must_use]
pub fn parse_retry_after(value: &str) -> Option<Duration> {
    let secs: u64 = value.trim().parse().ok()?;
    Some(Duration::from_secs(secs.clamp(1, RETRY_AFTER_MAX_SECS)))
}

#[must_use]
pub fn classify(status: u16, retry_after: Option<&str>) -> Outcome {
    let wait = retry_after.and_then(parse_retry_after);
    match status {
        200..=299 => Outcome::Sent,
        401 | 403 => Outcome::Auth,
        404 => Outcome::NotFound,
        409 => Outcome::Stale,
        400 | 413 | 422 => Outcome::Permanent,
        429 => Outcome::Retry(Some(
            wait.unwrap_or(Duration::from_secs(RATE_LIMIT_DEFAULT_SECS)),
        )),
        // 408, 5xx, redirects and anything unexpected: try again later
        _ => Outcome::Retry(wait),
    }
}

#[cfg(test)]
mod tests {
    use super::{classify, parse_retry_after, Outcome};
    use std::time::Duration;

    #[test]
    fn success_codes_are_sent() {
        assert_eq!(classify(200, None), Outcome::Sent);
        assert_eq!(classify(201, None), Outcome::Sent);
    }

    #[test]
    fn only_the_bad_reading_statuses_are_permanent() {
        for status in [400, 413, 422] {
            assert_eq!(classify(status, None), Outcome::Permanent, "{status}");
        }
    }

    #[test]
    fn other_client_errors_are_retried_and_never_throw_data_away() {
        for status in [402, 405, 406, 410, 414, 415, 418, 426, 451] {
            assert_eq!(classify(status, None), Outcome::Retry(None), "{status}");
        }
    }

    #[test]
    fn a_404_is_a_wrong_address_and_not_a_bad_reading() {
        assert_eq!(classify(404, None), Outcome::NotFound);
    }

    #[test]
    fn a_conflict_is_stale_and_not_permanent() {
        assert_eq!(classify(409, None), Outcome::Stale);
    }

    #[test]
    fn key_refusal_is_not_permanent() {
        assert_eq!(classify(401, None), Outcome::Auth);
        assert_eq!(classify(403, None), Outcome::Auth);
    }

    #[test]
    fn timeout_rate_limit_and_server_errors_retry() {
        assert_eq!(classify(408, None), Outcome::Retry(None));
        assert_eq!(classify(500, None), Outcome::Retry(None));
        assert_eq!(
            classify(503, Some("7")),
            Outcome::Retry(Some(Duration::from_secs(7)))
        );
        assert_eq!(classify(302, None), Outcome::Retry(None));
    }

    #[test]
    fn rate_limit_honours_retry_after() {
        assert_eq!(
            classify(429, Some("30")),
            Outcome::Retry(Some(Duration::from_secs(30)))
        );
        assert_eq!(
            classify(429, None),
            Outcome::Retry(Some(Duration::from_secs(60)))
        );
        assert_eq!(
            classify(429, Some("Wed, 21 Oct 2026 07:28:00 GMT")),
            Outcome::Retry(Some(Duration::from_secs(60)))
        );
    }

    #[test]
    fn retry_after_is_clamped() {
        assert_eq!(parse_retry_after("0"), Some(Duration::from_secs(1)));
        assert_eq!(parse_retry_after("999999"), Some(Duration::from_secs(3600)));
        assert_eq!(parse_retry_after("-5"), None);
        assert_eq!(parse_retry_after("abc"), None);
    }
}
