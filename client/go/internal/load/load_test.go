package load

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestPercentileNearestRank(t *testing.T) {
	var ms []time.Duration
	for i := 1; i <= 100; i++ {
		ms = append(ms, time.Duration(i)*time.Millisecond)
	}
	if got := Percentile(ms, 95); got != 95*time.Millisecond {
		t.Fatalf("p95 = %v", got)
	}
	if got := Percentile(ms, 50); got != 50*time.Millisecond {
		t.Fatalf("p50 = %v", got)
	}
	if got := Percentile(nil, 99); got != 0 {
		t.Fatalf("empty p99 = %v", got)
	}
}

func TestRunSeparatesAcceptedThrottledAndFailed(t *testing.T) {
	throttled := errors.New("429")
	result := Run(context.Background(), Options{Requests: 60, Concurrency: 8, IsThrottled: func(err error) bool { return err == throttled }},
		func(_ context.Context, i int) error {
			switch {
			case i%10 == 0:
				return errors.New("boom")
			case i%3 == 0:
				return throttled
			}
			return nil
		})
	if result.Requests() != 60 || result.Errors != 6 || result.Throttled != 18 || len(result.Latencies) != 36 {
		t.Fatalf("accepted %d throttled %d failed %d", len(result.Latencies), result.Throttled, result.Errors)
	}
	for _, want := range []string{"36 accepted", "18 throttled (429)", "6 failed"} {
		if !strings.Contains(result.Summary(), want) {
			t.Fatalf("%q missing from %s", want, result.Summary())
		}
	}
}

func TestThrottledPostsAreNotInTheLatency(t *testing.T) {
	throttled := errors.New("429")
	result := Run(context.Background(), Options{Requests: 10, Concurrency: 1, IsThrottled: func(err error) bool { return err == throttled }},
		func(_ context.Context, i int) error {
			if i < 9 {
				return throttled // quick refusals
			}
			time.Sleep(20 * time.Millisecond)
			return nil
		})
	if len(result.Latencies) != 1 || Percentile(result.Latencies, 50) < 20*time.Millisecond {
		t.Fatalf("a refusal must not make the latency look fast: %v", result.Latencies)
	}
}

func TestRunPacesRequestsWithTheGivenSleep(t *testing.T) {
	var slept []time.Duration
	Run(context.Background(), Options{Requests: 4, Concurrency: 1, Interval: 2 * time.Second, Sleep: func(_ context.Context, d time.Duration) error {
		slept = append(slept, d)
		return nil
	}}, func(context.Context, int) error { return nil })
	if len(slept) != 3 || slept[0] != 2*time.Second {
		t.Fatalf("%v", slept)
	}
}

func TestRunStopsWhenTheContextIsCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	calls := 0
	result := Run(ctx, Options{Requests: 100, Concurrency: 1, Interval: time.Second, Sleep: func(_ context.Context, d time.Duration) error {
		cancel()
		return ctx.Err()
	}}, func(context.Context, int) error { calls++; return nil })
	if result.Requests() >= 100 || calls >= 100 {
		t.Fatalf("not stopped: %d", calls)
	}
}
