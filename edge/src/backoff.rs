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

#[cfg(test)]
mod tests {
    use super::delay;
    use std::time::Duration;

    #[test]
    fn doubles_then_caps() {
        let secs: Vec<u64> = (1..=8).map(|a| delay(a).as_secs()).collect();
        assert_eq!(secs, vec![1, 2, 4, 8, 16, 32, 60, 60]);
    }

    #[test]
    fn huge_attempts_stay_capped() {
        assert_eq!(delay(u32::MAX), Duration::from_secs(60));
    }
}
