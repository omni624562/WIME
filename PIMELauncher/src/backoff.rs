use std::time::Duration;

/// Restart delays that grow while something keeps failing and start over once
/// it has run fine for a while.
///
/// The launcher used to restart a crashed backend after a fixed 1 s (and the
/// worker, and a pipe it could not create): a backend that dies right away --
/// e.g. on a damaged user dictionary -- was restarted forever, once a second.
/// Now the delay doubles up to `max`; a run of `healthy_after` resets it.
pub struct Backoff {
    base: Duration,
    max: Duration,
    healthy_after: Duration,
    failures: u32,
}

impl Backoff {
    pub fn new(base: Duration, max: Duration, healthy_after: Duration) -> Self {
        Self { base, max, healthy_after, failures: 0 }
    }

    /// The usual restart policy: 1 s, 2 s, 4 s ... up to 30 s; a minute of
    /// uptime counts as healthy.
    pub fn for_restarts() -> Self {
        Self::new(Duration::from_secs(1), Duration::from_secs(30), Duration::from_secs(60))
    }

    /// The delay before the next start, after a run that lasted `ran_for`
    /// (zero when it did not even start).
    pub fn next_delay(&mut self, ran_for: Duration) -> Duration {
        if ran_for >= self.healthy_after {
            self.failures = 0;
        }
        let delay = self.base.saturating_mul(1u32 << self.failures.min(16)).min(self.max);
        self.failures = self.failures.saturating_add(1);
        delay
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delays_double_up_to_the_maximum() {
        let mut b = Backoff::for_restarts();
        let delays: Vec<u64> = (0..8).map(|_| b.next_delay(Duration::ZERO).as_secs()).collect();
        assert_eq!(delays, vec![1, 2, 4, 8, 16, 30, 30, 30]);
    }

    #[test]
    fn a_healthy_run_starts_over() {
        let mut b = Backoff::for_restarts();
        for _ in 0..5 {
            b.next_delay(Duration::from_secs(2));
        }
        assert_eq!(b.next_delay(Duration::from_secs(61)), Duration::from_secs(1));
        assert_eq!(b.next_delay(Duration::from_secs(3)), Duration::from_secs(2));
    }

    #[test]
    fn many_failures_do_not_overflow() {
        let mut b = Backoff::for_restarts();
        for _ in 0..1000 {
            assert!(b.next_delay(Duration::ZERO) <= Duration::from_secs(30));
        }
    }
}
