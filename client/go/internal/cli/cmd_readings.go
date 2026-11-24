package cli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:    []string{"readings", "latest"},
		summary: "show a machine's newest reading (or the newest few)",
		desc: "Shows the newest reading of a machine, by id or name. With --count it shows that many of the newest, oldest first. " +
			"A table shows the columns that have values: choose them with --fields or see every one with --all.",
		examples: []string{"phaemosctl readings latest press-01", "phaemosctl readings latest press-01 --count 20 --fields temperature,vibration_x"},
		args:     "<device>", minArgs: 1, maxArgs: 1, needsToken: true,
		flags: func(fs *flag.FlagSet) {
			fs.Int("count", 1, "how many of the newest readings (1 to 200)")
			fs.String("fields", "", "comma-separated columns to show")
			fs.Bool("all", false, "show every column that has a value")
		},
		run: runReadingsLatest,
	})
	register(&command{
		path:    []string{"readings", "tail"},
		summary: "follow a machine's new readings until you stop it",
		desc: "Shows the newest readings and then polls for new ones every --interval (default 5 s, at least 1 s) until you press " +
			"Ctrl+C or --timeout passes. It polls and does not use the live socket, because an API token may not use the socket " +
			"(only a signed-in session can). A failed poll is retried with a longer wait each time (up to 60 s), a 429 waits for the " +
			"server's Retry-After and ten failures in a row end the command with exit code 8. The route allows 600 reads a minute for an " +
			"address, which the default interval uses a fiftieth of. It shows a table or jsonl, not json.",
		examples: []string{"phaemosctl readings tail press-01", "phaemosctl readings tail press-01 --interval 2s --output jsonl | jq .temperature"},
		args:     "<device>", minArgs: 1, maxArgs: 1, needsToken: true,
		timeout:               -1,
		followsUntilCancelled: true,
		flags: func(fs *flag.FlagSet) {
			fs.Duration("interval", 5*time.Second, "time between polls (at least 1s)")
			fs.Int("lines", 10, "how many recent readings to show first (0 to 200)")
			fs.String("fields", "", "comma-separated columns to show")
		},
		run: runReadingsTail,
	})
	register(&command{
		path:    []string{"readings", "export"},
		summary: "write a machine's readings to a CSV file",
		desc: "Streams a machine's readings between --from and --to (at most 31 days, oldest first) to a file as the server sends them, " +
			"so a large export never sits in memory. The file is not overwritten unless you pass --force. A time is an RFC 3339 time " +
			"(2026-11-21T14:00:00Z), a date (2026-11-21, meaning midnight UTC) or an age such as 24h or 7d before now. --out - writes " +
			"to standard output. A failed export removes its partial file.",
		examples: []string{
			"phaemosctl readings export press-01 --from 7d --out press-01.csv",
			"phaemosctl readings export press-01 --from 2026-11-01 --to 2026-11-08 --out week.csv --force",
		},
		args: "<device>", minArgs: 1, maxArgs: 1, needsToken: true,
		timeout: 10 * time.Minute,
		flags: func(fs *flag.FlagSet) {
			fs.String("from", "", "start of the window (required)")
			fs.String("to", "", "end of the window (default now)")
			fs.String("out", "", "file to write or - for standard output (required)")
			fs.Bool("force", false, "overwrite the file if it exists")
		},
		run: runReadingsExport,
	})
}

func parseWhen(text string, now time.Time) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339, text); err == nil {
		return t, nil
	}
	if t, err := time.Parse("2006-01-02", text); err == nil {
		return t, nil
	}
	if strings.HasSuffix(text, "d") {
		if n, err := strconv.Atoi(strings.TrimSuffix(text, "d")); err == nil && n >= 0 {
			return now.Add(-time.Duration(n) * 24 * time.Hour), nil
		}
	}
	if d, err := time.ParseDuration(text); err == nil && d >= 0 {
		return now.Add(-d), nil
	}
	return time.Time{}, usageErr("%q is not a time: use 2026-11-21T14:00:00Z, 2026-11-21 or an age such as 24h or 7d", text)
}

var readingPriority = []string{"temperature", "humidity", "pressure", "vibration_x", "vibration_y", "vibration_z", "current_ma", "bus_voltage", "gas_level", "light_level", "anomaly_score", "is_anomaly"}

var readingSkip = map[string]bool{"id": true, "device_id": true, "recorded_at": true, "node_type": true, "created_at": true}

func readingColumns(rows []api.Reading, fields string, all bool) []string {
	if fields != "" {
		var cols []string
		for _, f := range strings.Split(fields, ",") {
			if f = strings.TrimSpace(f); f != "" {
				cols = append(cols, f)
			}
		}
		return cols
	}
	present := map[string]bool{}
	for _, row := range rows {
		for k, v := range row.Fields {
			if v != nil && !readingSkip[k] {
				present[k] = true
			}
		}
	}
	var cols []string
	for _, k := range readingPriority {
		if present[k] {
			cols = append(cols, k)
			delete(present, k)
		}
	}
	rest := make([]string, 0, len(present))
	for k := range present {
		rest = append(rest, k)
	}
	sort.Strings(rest)
	cols = append(cols, rest...)
	if !all && len(cols) > 8 {
		cols = cols[:8]
	}
	return cols
}

func fieldText(v any) string {
	switch x := v.(type) {
	case nil:
		return "-"
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(x)
	case string:
		return x
	}
	return fmt.Sprint(v)
}

func reverseRaw[T any](items []T) {
	for i, j := 0, len(items)-1; i < j; i, j = i+1, j-1 {
		items[i], items[j] = items[j], items[i]
	}
}

func runReadingsLatest(r *runCtx) error {
	count := r.integer("count")
	if count < 1 || count > 200 {
		return usageErr("--count must be between 1 and 200")
	}
	dev, _, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	if count == 1 {
		raw, err := r.client.LatestReadingRaw(r.ctx, dev.ID)
		if err != nil {
			return err
		}
		if r.format != formatTable {
			return r.emitRaw(raw)
		}
		var row api.Reading
		if err := row.UnmarshalJSON(raw); err != nil {
			return err
		}
		k := &kv{}
		k.add("machine", dev.Name)
		k.add("recorded", timeFmt(row.RecordedAt, r.loc()))
		k.add("node type", first(row.NodeType, "-"))
		keys := make([]string, 0, len(row.Fields))
		for key, v := range row.Fields {
			if v != nil && !readingSkip[key] {
				keys = append(keys, key)
			}
		}
		sort.Strings(keys)
		for _, key := range keys {
			k.add(key, fieldText(row.Fields[key]))
		}
		renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
		return nil
	}
	items, _, err := r.client.Readings(r.ctx, dev.ID, api.ReadingsOptions{Limit: count})
	if err != nil {
		return err
	}
	reverseRaw(items)
	if r.format != formatTable {
		return writeList(r.out(), items, r.format)
	}
	rows, err := api.DecodeAll[api.Reading](items)
	if err != nil {
		return err
	}
	cols := readingColumns(rows, r.str("fields"), r.boolean("all"))
	t := &table{Headers: append([]string{"TIME", "NODE"}, upper(cols)...)}
	for _, row := range rows {
		cells := []cell{plain(timeFmt(row.RecordedAt, r.loc())), plain(first(row.NodeType, "-"))}
		for _, c := range cols {
			cells = append(cells, plain(fieldText(row.Fields[c])))
		}
		t.add(cells...)
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

func upper(items []string) []string {
	out := make([]string, len(items))
	for i, s := range items {
		out[i] = strings.ToUpper(s)
	}
	return out
}

func (r *runCtx) sleep(d time.Duration) error {
	clock := r.app.io.Clock
	if clock == nil {
		clock = api.SystemClock()
	}
	return clock.Sleep(r.ctx, d)
}

// tailer holds what readings tail needs between polls.
type tailer struct {
	r       *runCtx
	dev     api.Device
	cols    []string
	started bool
	last    time.Time
	seen    map[string]bool
}

func (t *tailer) print(items []api.Reading, raws []jsonRaw) {
	for i, row := range items {
		if t.r.format == formatJSONL {
			_ = compactJSON(t.r.out(), raws[i])
			continue
		}
		if !t.started {
			if t.cols == nil {
				t.cols = readingColumns(items, t.r.str("fields"), false)
			}
			head := append([]string{"TIME", "NODE"}, upper(t.cols)...)
			t.line(head)
			t.started = true
		}
		cells := []string{timeFmt(row.RecordedAt, t.r.loc()), first(row.NodeType, "-")}
		for _, c := range t.cols {
			cells = append(cells, fieldText(row.Fields[c]))
		}
		t.line(cells)
	}
}

type jsonRaw = []byte

func (t *tailer) line(cells []string) {
	if !t.r.app.io.OutTTY {
		fmt.Fprintln(t.r.out(), strings.Join(cells, "\t"))
		return
	}
	var b strings.Builder
	for i, c := range cells {
		w := 12
		if i == 0 {
			w = 24
		}
		if i == len(cells)-1 {
			b.WriteString(c)
		} else {
			fmt.Fprintf(&b, "%-*s  ", w, c)
		}
	}
	fmt.Fprintln(t.r.out(), b.String())
}

func (t *tailer) remember(row api.Reading) {
	if row.RecordedAt.After(t.last) {
		t.last = row.RecordedAt.Time
		t.seen = map[string]bool{}
	}
	if row.RecordedAt.Time.Equal(t.last) {
		t.seen[row.ID] = true
	}
}

func decodeReadings(raws [][]byte) ([]api.Reading, error) {
	rows := make([]api.Reading, 0, len(raws))
	for _, raw := range raws {
		var row api.Reading
		if err := row.UnmarshalJSON(raw); err != nil {
			return nil, err
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func toBytes(items [][]byte) [][]byte { return items }

func runReadingsTail(r *runCtx) error {
	if r.format == formatJSON {
		return usageErr("readings tail never ends, so it cannot make one JSON document: use --output jsonl")
	}
	interval := r.duration("interval")
	if interval < time.Second {
		return usageErr("--interval must be at least 1s, so one tail cannot use up the read limit")
	}
	lines := r.integer("lines")
	if lines < 0 || lines > 200 {
		return usageErr("--lines must be between 0 and 200")
	}
	dev, _, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	t := &tailer{r: r, dev: dev, seen: map[string]bool{}, last: r.app.io.Now()}
	if lines > 0 {
		items, _, err := r.client.Readings(r.ctx, dev.ID, api.ReadingsOptions{Limit: lines})
		if err != nil {
			return err
		}
		reverseRaw(items)
		raws := make([][]byte, len(items))
		for i := range items {
			raws[i] = items[i]
		}
		rows, err := decodeReadings(raws)
		if err != nil {
			return err
		}
		t.print(rows, raws)
		for _, row := range rows {
			t.remember(row)
		}
	}
	failures := 0
	wait := interval
	for {
		if err := r.sleep(wait); err != nil {
			return err
		}
		fresh, err := t.poll()
		if err != nil {
			ee := classify(err)
			if ee.Code == ExitNotSignedIn || ee.Code == ExitForbidden || ee.Code == ExitNotFound || ee.Code == ExitUsage {
				return err
			}
			failures++
			if failures >= 10 {
				return newExit(ExitUnavailable, "gave up after %d failed polls in a row: %s", failures, ee.Message)
			}
			wait = min(interval<<min(failures, 6), 60*time.Second)
			var ae *api.Error
			if errors.As(err, &ae) && ae.RetryAfter > wait && ae.RetryAfter <= 5*time.Minute {
				wait = ae.RetryAfter
			}
			r.warn("poll failed (%s): trying again in %d s", ee.Message, int(wait.Seconds()))
			continue
		}
		failures, wait = 0, interval
		_ = fresh
	}
}

// poll fetches readings newer than the last one shown and prints them oldest first.
func (t *tailer) poll() (int, error) {
	var collected []api.Reading
	var raws [][]byte
	cursor := ""
	for page := 0; page < 5; page++ {
		// a full page carries the cursor of its last row in X-Next-Before: send it back as before
		items, next, err := t.r.client.Readings(t.r.ctx, t.dev.ID, api.ReadingsOptions{Limit: 500, Before: cursor, From: t.last})
		if err != nil {
			return 0, err
		}
		for _, raw := range items {
			var row api.Reading
			if err := row.UnmarshalJSON(raw); err != nil {
				return 0, err
			}
			if !t.seen[row.ID] {
				collected = append(collected, row)
				raws = append(raws, raw)
			}
		}
		if len(items) < 500 || next == "" {
			break
		}
		cursor = next
		if page == 4 {
			t.r.warn("more than 2500 new readings arrived in one interval: some are not shown. Use a shorter --interval")
		}
	}
	reverseRaw(collected)
	reverseRaw(raws)
	t.print(collected, raws)
	for _, row := range collected {
		t.remember(row)
	}
	return len(collected), nil
}

func runReadingsExport(r *runCtx) error {
	out := r.str("out")
	if out == "" {
		return usageErr("--out is required: a file name or - for standard output")
	}
	if r.str("from") == "" {
		return usageErr("--from is required: the export covers at most 31 days")
	}
	now := r.app.io.Now()
	from, err := parseWhen(r.str("from"), now)
	if err != nil {
		return err
	}
	to := time.Time{}
	if r.str("to") != "" {
		if to, err = parseWhen(r.str("to"), now); err != nil {
			return err
		}
	}
	end := to
	if end.IsZero() {
		end = now
	}
	if !end.After(from) {
		return usageErr("--to must be later than --from")
	}
	if end.Sub(from) > api.ExportMaxSpan {
		return usageErr("an export covers at most 31 days: shorten the window")
	}
	dev, _, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	// the destination is chosen before anything is downloaded, so a refusal costs nothing
	var dest io.Writer
	var finish func(ok bool) error
	switch {
	case out == "-":
		dest, finish = r.out(), func(bool) error { return nil }
	case r.boolean("force"):
		dir := filepath.Dir(out)
		tmp, err := os.CreateTemp(dir, ".phaemos-export-*")
		if err != nil {
			return err
		}
		dest = tmp
		finish = func(ok bool) error {
			if cerr := tmp.Close(); ok && cerr != nil {
				ok = false
				err = cerr
			}
			if !ok {
				_ = os.Remove(tmp.Name())
				return err
			}
			return os.Rename(tmp.Name(), out)
		}
	default:
		f, err := os.OpenFile(out, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		if err != nil {
			if errors.Is(err, os.ErrExist) {
				return usageErr("%s already exists: choose another name or pass --force to overwrite it", out)
			}
			return err
		}
		dest = f
		finish = func(ok bool) error {
			cerr := f.Close()
			if !ok {
				_ = os.Remove(out)
				return nil
			}
			return cerr
		}
	}
	body, err := r.client.Export(r.ctx, dev.ID, from, to)
	if err != nil {
		_ = finish(false)
		return err
	}
	defer body.Close()
	n, copyErr := copyWithContext(r.ctx, dest, body)
	if copyErr != nil {
		_ = finish(false)
		return &api.Error{Method: "GET", Path: "/api/v1/telemetry/export", Err: fmt.Errorf("the export stopped after %d bytes: %v", n, copyErr)}
	}
	if err := finish(true); err != nil {
		return err
	}
	if out != "-" {
		r.info("Wrote %d bytes to %s.", n, out)
	}
	return nil
}

func copyWithContext(ctx context.Context, dst io.Writer, src io.Reader) (int64, error) {
	buf := make([]byte, 64<<10)
	var total int64
	for {
		if err := ctx.Err(); err != nil {
			return total, err
		}
		n, err := src.Read(buf)
		if n > 0 {
			if _, werr := dst.Write(buf[:n]); werr != nil {
				return total, werr
			}
			total += int64(n)
		}
		if err == io.EOF {
			return total, nil
		}
		if err != nil {
			return total, err
		}
	}
}
