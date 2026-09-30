package load

import (
	"context"
	"errors"
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

func TestRunCountsEveryRequestAndError(t *testing.T) {
	result := Run(context.Background(), 50, 8, func(_ context.Context, i int) error {
		if i%10 == 0 {
			return errors.New("boom")
		}
		return nil
	})
	if len(result.Latencies) != 50 || result.Errors != 5 {
		t.Fatalf("got %d latencies and %d errors", len(result.Latencies), result.Errors)
	}
}
