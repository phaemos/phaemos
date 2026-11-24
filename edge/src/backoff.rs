//! retry timing for forwarding after a failure.

use std::time::Duration;

const BASE_SECS: u64 = 1;
const MAX_SECS: u64 = 60;

/// delay before retry number `attempt` (starting at 1): 1, 2, 4, 8 seconds and so on,
/// capped at one minute so a long outage is noticed quickly once it ends.
#[must_use]
pub fn delay(attempt: u32) -> Duration {
    let exponent = attempt.saturating_sub(1).min(16);
    Duration::from_secs((BASE_SECS << exponent).min(MAX_SECS))
}

const AUTH_BASE_SECS: u64 = 300;
const AUTH_MAX_SECS: u64 = 3600;

/// delay after the API refused the key, attempt 1 onwards: 5 minutes, then 10, 20, 40 and so on
/// up to an hour. A wrong key will not fix itself, so there is no point asking every minute.
#[must_use]
pub fn auth_delay(attempt: u32) -> Duration {
    let exponent = attempt.saturating_sub(1).min(16);
    Duration::from_secs((AUTH_BASE_SECS << exponent).min(AUTH_MAX_SECS))
}

#[cfg(test)]
mod tests {
    use super::{auth_delay, delay};
    use std::time::Duration;

    #[test]
    fn doubles_then_caps() {
        let secs: Vec<u64> = (1..=8).map(|a| delay(a).as_secs()).collect();
        assert_eq!(secs, vec![1, 2, 4, 8, 16, 32, 60, 60]);
    }

    #[test]
    fn key_refusal_waits_much_longer_and_caps_at_an_hour() {
        let secs: Vec<u64> = (1..=6).map(|a| auth_delay(a).as_secs()).collect();
        assert_eq!(secs, vec![300, 600, 1200, 2400, 3600, 3600]);
        assert_eq!(auth_delay(u32::MAX), Duration::from_secs(3600));
    }

    #[test]
    fn huge_attempts_stay_capped() {
        assert_eq!(delay(u32::MAX), Duration::from_secs(60));
    }
}
