// Package load drives concurrent requests at the ingest endpoint and reports latency percentiles.
package load

import (
	"context"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"
)

// Result holds every request's latency and how many failed.
type Result struct {
	Latencies []time.Duration
	Errors    int
	Elapsed   time.Duration
}

// Run sends `requests` calls through `concurrency` workers.
func Run(ctx context.Context, requests, concurrency int, call func(context.Context, int) error) Result {
	jobs := make(chan int)
	var mu sync.Mutex
	var wg sync.WaitGroup
	result := Result{}
	start := time.Now()
	for w := 0; w < concurrency; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				began := time.Now()
				err := call(ctx, i)
				took := time.Since(began)
				mu.Lock()
				result.Latencies = append(result.Latencies, took)
				if err != nil {
					result.Errors++
				}
				mu.Unlock()
			}
		}()
	}
	for i := 0; i < requests; i++ {
		jobs <- i
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

// Summary formats the numbers that matter for the ingest latency budget.
func (r Result) Summary() string {
	rate := float64(len(r.Latencies)) / r.Elapsed.Seconds()
	return fmt.Sprintf("%d requests, %d errors, %.1f req/s, p50 %v, p95 %v, p99 %v",
		len(r.Latencies), r.Errors, rate,
		Percentile(r.Latencies, 50).Round(time.Millisecond),
		Percentile(r.Latencies, 95).Round(time.Millisecond),
		Percentile(r.Latencies, 99).Round(time.Millisecond))
}
