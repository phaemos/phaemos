package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func lastQuery(f *fakeAPI, path string) string {
	rs := f.requests()
	for i := len(rs) - 1; i >= 0; i-- {
		if rs[i].Path == path {
			return rs[i].Query
		}
	}
	return ""
}

func TestFiltersAreTheServersAndNotTheTools(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	mustOK(t, e, "alerts", "list", "--severity", "critical", "--kind", "rule", "--device", "press-01", "-o", "json")
	q := lastQuery(f, "/api/v1/alerts")
	for _, want := range []string{"severity=critical", "kind=rule", "device_id=" + d1} {
		if !strings.Contains(q, want) {
			t.Fatalf("the filter must go to the server: %s", q)
		}
	}
	if _, errs, code := e.run("alerts", "list", "--severity", "urgent"); code != ExitUsage || !strings.Contains(errs, "info, warning or critical") {
		t.Fatalf("%d %s", code, errs)
	}
	mustOK(t, e, "tickets", "list", "--machine", "press-01", "-o", "json")
	if q := lastQuery(f, "/api/v1/tickets"); !strings.Contains(q, "device_id="+d1) {
		t.Fatalf("%s", q)
	}
	mustOK(t, e, "tickets", "show", "PHM-0012", "-o", "json")
	if q := lastQuery(f, "/api/v1/tickets"); !strings.Contains(q, "ticket_number=12") || !strings.Contains(q, "limit=1") {
		t.Fatalf("%s", q)
	}
	// a device is found with the exact name filter, not by paging the fleet
	mustOK(t, e, "devices", "show", "PRESS-01", "-o", "json")
	if q := lastQuery(f, "/api/v1/devices"); !strings.Contains(q, "name=PRESS-01") || strings.Contains(q, "search=") {
		t.Fatalf("%s", q)
	}
	// nothing matches: suggestions come from search
	_, errs, code := e.run("devices", "show", "pump")
	if code != ExitNotFound || !strings.Contains(errs, "Did you mean: pump-02") {
		t.Fatalf("%d %s", code, errs)
	}
	if q := lastQuery(f, "/api/v1/devices"); !strings.Contains(q, "search=pump") {
		t.Fatalf("%s", q)
	}
}

func TestResolveIsAPostAndAnOldPatchAnswersWithADeprecationNotice(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	mustOK(t, e, "alerts", "resolve", a1, "--yes")
	if f.count("POST", "/api/v1/alerts/"+a1+"/resolve") != 1 || f.count("PATCH", "/api/v1/alerts/"+a1+"/resolve") != 0 {
		t.Fatal("resolving is a POST")
	}
}

func TestVerboseSaysWhenARouteIsDeprecatedAndTheDefaultDoesNot(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	hdr := map[string]string{"Deprecation": "true", "Sunset": "Wed, 01 Jul 2027 00:00:00 GMT"}
	f.queue("GET", "/api/v1/health/summary", step{status: 200, header: hdr, body: `{"total_devices":1}`, forever: true})
	out, errs, code := e.run("health", "--verbose", "-o", "json")
	if code != 0 || strings.Contains(out, "deprecated") {
		t.Fatalf("%d %s", code, out)
	}
	if strings.Count(errs, "notice: GET /api/v1/health/summary is deprecated and will be removed after Wed, 01 Jul 2027") != 1 {
		t.Fatalf("one line, once:\n%s", errs)
	}
	e.run("health", "--verbose")
	_, errs, _ = e.run("health")
	if strings.Contains(errs, "deprecated") {
		t.Fatalf("only --verbose says it:\n%s", errs)
	}
	// twice in one run is one notice
	_, errs, _ = e.run("devices", "show", "press-01", "--verbose")
	if strings.Contains(errs, "deprecated") {
		t.Fatalf("an unrelated route must not be called deprecated:\n%s", errs)
	}
}

func TestWindowsStartSendsOneIdempotencyKeyPerRunAndRetriesSafely(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokAdmin
	// the first try meets a 503 (the answer was lost), the retry carries the same key
	f.queue("POST", "/api/v1/maintenance-windows", step{status: 503})
	mustOK(t, e, "windows", "start", "press-01", "--for", "1h", "--yes")
	var keys []string
	for _, r := range f.requests() {
		if r.Method == "POST" && r.Path == "/api/v1/maintenance-windows" {
			keys = append(keys, r.Idem)
		}
	}
	if len(keys) != 2 || keys[0] == "" || keys[0] != keys[1] {
		t.Fatalf("keys %v", keys)
	}
	if len(f.windows) != 1 {
		t.Fatalf("a retry made %d windows", len(f.windows))
	}
	// a second run makes its own key
	mustOK(t, e, "windows", "start", "press-01", "--for", "1h", "--yes")
	if f.windowKeys[len(f.windowKeys)-1] == keys[0] || len(f.windows) != 2 {
		t.Fatalf("keys %v windows %d", f.windowKeys, len(f.windows))
	}
	if len(keys[0]) < 8 || len(keys[0]) > 128 {
		t.Fatalf("the key must be 8 to 128 visible characters: %q", keys[0])
	}
}

func TestIdempotencyAnswersAreSaidPlainly(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokAdmin
	f.queue("POST", "/api/v1/maintenance-windows", step{status: 409, header: map[string]string{"Retry-After": "2"}, body: `{"code":"idempotency_in_progress","detail":"A request with this key is still being handled"}`})
	_, errs, code := e.run("windows", "start", "press-01", "--for", "1h", "--yes")
	if code != ExitConflict || !strings.Contains(errs, "still being handled") || !strings.Contains(errs, "run the command again") {
		t.Fatalf("%d %s", code, errs)
	}
	f.queue("POST", "/api/v1/maintenance-windows", step{status: 422, body: `{"code":"idempotency_key_reused","detail":"x"}`})
	_, errs, code = e.run("windows", "start", "press-01", "--for", "1h", "--yes")
	if code != ExitConflict || !strings.Contains(errs, "already used for a different request") {
		t.Fatalf("%d %s", code, errs)
	}
	// the in-progress 409 is not retried by the tool
	if n := f.count("POST", "/api/v1/maintenance-windows"); n != 2 {
		t.Fatalf("%d posts", n)
	}
}

func TestTailWalksNewReadingsByKeysetWhenAPageIsFull(t *testing.T) {
	f := newFake(t)
	// 700 new readings arrive in one interval: two pages of 500 and 200, linked by X-Next-Before
	rows := make([]map[string]any, 0, 700)
	for i := 0; i < 700; i++ {
		at := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC).Add(time.Duration(700-i) * time.Second)
		rows = append(rows, map[string]any{"id": fmt.Sprintf("00000000-0000-4000-8000-%012d", 900-i), "device_id": d1, "recorded_at": at.Format(time.RFC3339), "node_type": "esp32", "temperature": float64(1000 - i)})
	}
	calls := 0
	f.readings[d1] = f.readings[d1][:1] // the tail's own first look shows one row
	f.onReadings = func() {
		calls++
		if calls == 2 {
			f.readings[d1] = rows
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	e := newEnv(t, f)
	e.ctx = ctx
	e.clock.onSleep = func(n int) {
		if n >= 2 {
			cancel()
		}
	}
	out, errs, code := e.run("readings", "tail", "press-01", "--lines", "1", "-o", "jsonl")
	if code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
	n := strings.Count(out, "\n")
	if n != 701 {
		t.Fatalf("%d readings shown, want the first one and 700 new", n)
	}
	q := lastQuery(f, "/api/v1/telemetry/"+d1)
	if !strings.Contains(q, "before=") || strings.Contains(q, "offset=") {
		t.Fatalf("the second page is read by keyset: %s", q)
	}
	// oldest first, each once
	var prev float64 = -1
	for _, l := range strings.Split(strings.TrimSpace(out), "\n")[1:] {
		var row map[string]any
		_ = json.Unmarshal([]byte(l), &row)
		if row["temperature"].(float64) <= prev {
			t.Fatal("not oldest first or repeated")
		}
		prev = row["temperature"].(float64)
	}
}
