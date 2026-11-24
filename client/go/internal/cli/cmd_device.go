package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math/rand"
	"sync/atomic"
	"time"

	"github.com/phaemos/client/go/internal/api"
	"github.com/phaemos/client/go/internal/load"
)

func init() {
	deviceFlags := func(fs *flag.FlagSet) {
		fs.String("key", "", "device key (prefer PHAEMOS_DEVICE_KEY: a flag shows in the process list)")
	}
	register(&command{
		path:    []string{"dev", "send"},
		summary: "post one reading as a device, with the device key",
		desc: "Posts one reading to the ingest route as a device, using the device key (not an API token). The reading is stamped " +
			"with boot, seq and up unless it already holds a boot or seq. boot is kept in a state folder (PHAEMOS_STATE_DIR, else " +
			"XDG_STATE_HOME/phaemos, else ~/.local/state/phaemos) in a file of mode 0600. This is the device path and is never retried. " +
			"It used to be called send and that name still works.",
		examples: []string{
			`PHAEMOS_DEVICE_KEY=<device key> phaemosctl dev send --json '{"device_id":"d1","temperature":24.1}'`,
			`phaemosctl dev send --url https://api.example.org --json '{"device_id":"d1","temperature":24.1}'`,
		},
		flags: func(fs *flag.FlagSet) {
			deviceFlags(fs)
			fs.String("json", "", "reading to send, as a JSON object")
		},
		run: runSend,
	})
	register(&command{
		path:    []string{"dev", "load"},
		summary: "measure the ingest route's answer time at a gentle rate",
		desc: "Posts synthetic readings under one device key and reports the answer time of the posts the server accepted, with the posts " +
			"the rate limiter refused (429) and the posts that failed counted apart and left out of the time. It measures the ingest path, " +
			"not the limiter: one device key is allowed 60 posts a minute, so the default is 30 a minute from one worker and a rate above 60 " +
			"will mostly be refused. It writes real rows, so it refuses a server that is not local unless you pass --yes-this-is-not-production. " +
			"Each post carries boot, seq and up. It is never retried. It exits 8 when a post failed, 7 when posts were throttled and 0 otherwise. " +
			"It used to be called load and that name still works.",
		examples: []string{
			"PHAEMOS_DEVICE_KEY=<device key> phaemosctl dev load --url http://localhost:8000 --requests 60",
			"phaemosctl dev load --url https://staging.example.org --rate 50 --yes-this-is-not-production",
		},
		flags: func(fs *flag.FlagSet) {
			deviceFlags(fs)
			fs.Int("requests", 20, "total posts")
			fs.Int("concurrency", 1, "parallel workers")
			fs.Int("rate", 30, "posts a minute, started evenly (0 for as fast as possible)")
			fs.Bool("yes-this-is-not-production", false, "allow a server that is not local")
		},
		run: runLoad,
	})
}

func (r *runCtx) deviceClient(required bool) (*api.Client, error) {
	key := r.str("key")
	if key == "" {
		key = r.app.io.Getenv("PHAEMOS_DEVICE_KEY")
	}
	if key == "" {
		if old := r.app.io.Getenv("PHAEMOS_API_KEY"); old != "" {
			key = old
			r.warn("PHAEMOS_API_KEY is the old name: use PHAEMOS_DEVICE_KEY")
		}
	}
	if key == "" && required {
		return nil, usageErr("this needs a device key: set PHAEMOS_DEVICE_KEY or pass --key")
	}
	client := api.New(r.url, key)
	client.Clock = r.app.io.Clock
	client.UserAgent = "phaemosctl/" + Version
	if r.app.io.HTTP != nil {
		client.HTTP = r.app.io.HTTP
	}
	if r.app.g.verbose {
		client.Trace = r.client.Trace
	}
	if key != "" {
		dir, err := api.StateDir(r.app.io.Getenv)
		if err != nil {
			dir = ""
		}
		counter := api.NewCounter(dir, key, r.app.io.Now())
		if dir == "" {
			counter.Warning = "no state folder (set PHAEMOS_STATE_DIR or HOME): boot comes from the clock and is not stored"
		}
		if counter.Warning != "" {
			r.warn("%s", counter.Warning)
		}
		client.Counter = counter
	}
	return client, nil
}

func runSend(r *runCtx) error {
	reading := map[string]any{}
	if err := json.Unmarshal([]byte(r.str("json")), &reading); err != nil {
		return usageErr("--json must be a JSON object")
	}
	client, err := r.deviceClient(false)
	if err != nil {
		return err
	}
	stored, err := client.SendReading(r.ctx, reading)
	if err != nil {
		return wrongAddress(err)
	}
	if api.IsDuplicate(stored) {
		r.info("duplicate: the API already has this exact post and stored nothing")
	}
	if r.format != formatTable {
		raw, _ := json.Marshal(stored)
		return r.emitRaw(raw)
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetIndent("", "  ")
	_ = enc.Encode(stored)
	_, err = r.out().Write(buf.Bytes())
	return err
}

func runLoad(r *runCtx) error {
	if !hostIsLocal(r.url) && !r.boolean("yes-this-is-not-production") {
		return usageErr("%s is not a local server and this writes real rows: pass --yes-this-is-not-production if you mean it", r.url)
	}
	client, err := r.deviceClient(true)
	if err != nil {
		return err
	}
	requests, concurrency, rate := r.integer("requests"), r.integer("concurrency"), r.integer("rate")
	if requests < 1 || concurrency < 1 || rate < 0 {
		return usageErr("--requests and --concurrency must be at least 1 and --rate cannot be negative")
	}
	opts := load.Options{
		Requests: requests, Concurrency: concurrency, Sleep: func(ctx context.Context, d time.Duration) error { return r.sleep(d) },
		IsThrottled: func(err error) bool {
			var ae *api.Error
			return errors.As(err, &ae) && ae.Status == 429
		},
	}
	if rate > 0 {
		opts.Interval = time.Minute / time.Duration(rate)
		if rate > 60 {
			r.warn("%d a minute is above the 60 a minute one device key is allowed: most posts will be throttled and are counted apart", rate)
		}
	}
	// a 404 on a post is a wrong address: it is reported once and the run stops, not tried again for every post
	loadCtx, stop := context.WithCancel(r.ctx)
	defer stop()
	var notFound atomic.Bool
	result := load.Run(loadCtx, opts, func(ctx context.Context, i int) error {
		_, err := client.SendReading(ctx, syntheticReading(i))
		var ae *api.Error
		if errors.As(err, &ae) && ae.Status == 404 {
			notFound.Store(true)
			stop()
		}
		return err
	})
	if notFound.Load() {
		return wrongAddress(&api.Error{Method: "POST", Path: "/api/v1/telemetry", Status: 404})
	}
	summary := result.Summary()
	if r.format != formatTable {
		raw, _ := json.Marshal(map[string]any{"requests": result.Requests(), "accepted": len(result.Latencies), "throttled": result.Throttled, "failed": result.Errors,
			"elapsed_ms": result.Elapsed.Milliseconds(), "summary": summary})
		if err := r.emitRaw(raw); err != nil {
			return err
		}
	} else {
		fmt.Fprintln(r.out(), summary)
	}
	switch {
	case result.Errors > 0:
		return newExit(ExitUnavailable, "%d of %d posts failed", result.Errors, result.Requests())
	case result.Throttled > 0:
		return newExit(ExitRateLimited, "%d of %d posts were throttled by the rate limiter: lower --rate", result.Throttled, result.Requests())
	}
	return nil
}

// wrongAddress turns a 404 on a post into the configuration fault it is.
func wrongAddress(err error) error {
	var ae *api.Error
	if errors.As(err, &ae) && ae.Status == 404 {
		return newExit(ExitNotFound, "the API answered 404 for the telemetry route: the address is wrong. Give the base address only (for example https://api.example.org), with no path and no trailing slash")
	}
	return err
}

func syntheticReading(i int) map[string]any {
	return map[string]any{
		"device_id":   fmt.Sprintf("load-%d", i),
		"node_type":   "esp32",
		"temperature": 24 + rand.Float64(),
		"humidity":    48 + 2*rand.Float64(),
		"vibration_x": 0.05 * rand.Float64(),
		"vibration_y": 0.05 * rand.Float64(),
		"vibration_z": 1.0,
	}
}

var _ = time.Second
