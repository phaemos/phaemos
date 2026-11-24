// Package load drives requests at the ingest endpoint and reports latency percentiles.
//
// It measures the server's answer time for posts it accepted. Posts the rate limiter refused (429) are
// counted apart and left out of the latency, because a refusal is quick and says nothing about the
// ingest path: counting them would make the limiter look like a fast server.
package load

import (
	"context"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"
)

// Result holds what the run saw.
type Result struct {
	// Latencies holds the time of every post that was accepted (no error).
	Latencies []time.Duration
	// Throttled counts posts the limiter refused (429). Their time is not in Latencies.
	Throttled int
	// Errors counts every other failure.
	Errors  int
	Elapsed time.Duration
}

// Requests is how many posts were attempted.
func (r Result) Requests() int { return len(r.Latencies) + r.Throttled + r.Errors }

// Options controls a run.
type Options struct {
	Requests    int
	Concurrency int
	// Interval is the pause between starting one post and the next. Zero means no pause.
	Interval time.Duration
	// Sleep waits for Interval. Nil means time.Sleep with the context honoured.
	Sleep func(ctx context.Context, d time.Duration) error
	// IsThrottled says whether an error is the limiter's 429.
	IsThrottled func(error) bool
}

// Run sends Requests calls through Concurrency workers.
func Run(ctx context.Context, o Options, call func(context.Context, int) error) Result {
	jobs := make(chan int)
	var mu sync.Mutex
	var wg sync.WaitGroup
	result := Result{}
	start := time.Now()
	for w := 0; w < max(o.Concurrency, 1); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				began := time.Now()
				err := call(ctx, i)
				took := time.Since(began)
				mu.Lock()
				switch {
				case err == nil:
					result.Latencies = append(result.Latencies, took)
				case o.IsThrottled != nil && o.IsThrottled(err):
					result.Throttled++
				default:
					result.Errors++
				}
				mu.Unlock()
			}
		}()
	}
	sleep := o.Sleep
	if sleep == nil {
		sleep = func(ctx context.Context, d time.Duration) error {
			t := time.NewTimer(d)
			defer t.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-t.C:
				return nil
			}
		}
	}
	for i := 0; i < o.Requests; i++ {
		if i > 0 && o.Interval > 0 {
			if err := sleep(ctx, o.Interval); err != nil {
				break
			}
		}
		select {
		case jobs <- i:
		case <-ctx.Done():
		}
		if ctx.Err() != nil {
			break
		}
	}
	close(jobs)
	wg.Wait()
	result.Elapsed = time.Since(start)
	return result
}

// Percentile returns the p-th percentile (0 to 100) using the nearest-rank method.
func Percentile(latencies []time.Duration, p float64) time.Duration {
	if len(latencies) == 0 {
		return 0
	}
	sorted := append([]time.Duration(nil), latencies...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })
	rank := int(math.Ceil(p / 100 * float64(len(sorted))))
	if rank < 1 {
		rank = 1
	}
	return sorted[rank-1]
}

// Summary formats the numbers. The latency figures are for accepted posts only.
func (r Result) Summary() string {
	rate := 0.0
	if r.Elapsed > 0 {
		rate = float64(r.Requests()) / r.Elapsed.Seconds()
	}
	return fmt.Sprintf("%d requests: %d accepted, %d throttled (429), %d failed. %.1f requests/s. accepted latency p50 %v, p95 %v, p99 %v",
		r.Requests(), len(r.Latencies), r.Throttled, r.Errors, rate,
		Percentile(r.Latencies, 50).Round(time.Millisecond),
		Percentile(r.Latencies, 95).Round(time.Millisecond),
		Percentile(r.Latencies, 99).Round(time.Millisecond))
}
