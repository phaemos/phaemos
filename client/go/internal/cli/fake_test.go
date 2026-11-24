package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

var update = flag.Bool("update", false, "rewrite the golden files")

const (
	tokRead    = "pht_rd01_READSECRETREADSECRETREADSECRET1234"
	tokOperate = "pht_op02_OPERATESECRETOPERATESECRET12345678"
	tokSoon    = "pht_sn03_SOONSECRETSOONSECRETSOONSECRET1234"
	tokAdmin   = "pht_ad04_ADMINSECRETADMINSECRETADMINSECRET1234"
	tokBad     = "pht_xx99_UNKNOWNSECRETUNKNOWNSECRET12345678"
	devKey     = "device-key-SECRET-9876"
)

var testNow = time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC)

type step struct {
	status int
	header map[string]string
	body   string
	// abort ends the connection after writing part of the body
	partial string
	abort   bool
	// forever keeps the step at the front of the queue
	forever bool
}

type record struct {
	Method, Path, Query, Auth, Key string
	// Idem is the Idempotency-Key header
	Idem string
}

// fakeAPI follows docs/api-reference.md and the token contract.
type fakeAPI struct {
	t        *testing.T
	srv      *httptest.Server
	mu       sync.Mutex
	records  []record
	script   map[string][]step // method+" "+path -> queued answers
	devices  []map[string]any
	alerts   []map[string]any
	tickets  []map[string]any
	readings map[string][]map[string]any
	// onReadings runs before each readings list is served
	onReadings func()
	resolved   map[string]bool
	exportRows int
	windows    []map[string]any
	revoked    map[string]bool
	// statusTime is the clock /status reports (zero: a fixed time)
	statusTime time.Time
	windowKeys []string
	idempotent map[string]map[string]any
}

func newFake(t *testing.T) *fakeAPI {
	f := &fakeAPI{t: t, script: map[string][]step{}, readings: map[string][]map[string]any{}, resolved: map[string]bool{}, revoked: map[string]bool{}, idempotent: map[string]map[string]any{}}
	f.seed()
	f.srv = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.srv.Close)
	return f
}

const (
	d1 = "11111111-1111-4111-8111-111111111111"
	d2 = "22222222-2222-4222-8222-222222222222"
	d3 = "33333333-3333-4333-8333-333333333333"
	d4 = "44444444-4444-4444-8444-444444444444"
	d5 = "55555555-5555-4555-8555-555555555555"
	a1 = "a1000000-0000-4000-8000-000000000001"
	a2 = "a2000000-0000-4000-8000-000000000002"
	a3 = "a3000000-0000-4000-8000-000000000003"
	a4 = "a4000000-0000-4000-8000-000000000004"
	t1 = "b1000000-0000-4000-8000-000000000001"
	t2 = "b2000000-0000-4000-8000-000000000002"
)

func (f *fakeAPI) seed() {
	f.devices = []map[string]any{
		{"id": d1, "name": "press-01", "location": "Bay A", "type": "esp32", "status": "online", "last_seen": "2026-11-22T11:59:55+00:00",
			"firmware_version": "2.4.1", "created_at": "2026-01-01T00:00:00Z", "owner_name": "Sam", "tags": []string{"pump-room"},
			"expected_interval_s": 5, "link_state": "online", "seconds_since_last_post": 5,
			"model":            map[string]any{"state": "ready", "scope": "machine", "hours_collected": 336.0, "hours_needed": 24.0, "false_alerts_per_week": 0.0, "trained_at": "2026-11-21T04:10:00+00:00"},
			"replay_protected": true, "last_boot": 7, "last_seq": 1042, "replay_refused": 0, "replay_status": "Replay protection is on.",
			"health": map[string]any{"boot_count": 7, "uptime_s": 3600, "reset_reason": "poweron", "rssi": -61, "faults": map[string]any{"bme280": "missing"}, "lost_posts": 3}},
		{"id": d2, "name": "pump-02", "location": nil, "type": "stm32", "status": "offline", "last_seen": "2026-11-22T09:00:00",
			"firmware_version": nil, "created_at": "2026-02-01T00:00:00Z", "owner_name": nil, "tags": []string{},
			"expected_interval_s": 5, "link_state": "offline", "seconds_since_last_post": 10800,
			"model":            map[string]any{"state": "learning", "scope": nil, "hours_collected": 9.5, "hours_needed": 24.0, "false_alerts_per_week": nil, "trained_at": nil},
			"replay_protected": false, "last_boot": nil, "last_seq": nil, "replay_refused": 0, "health": nil},
		{"id": d3, "name": "Press-01b", "location": "Bay B", "type": "esp32", "status": "online", "last_seen": "2026-11-22T11:59:30Z",
			"tags": []string{"pump-room", "spare"}, "expected_interval_s": 5, "link_state": "late", "seconds_since_last_post": 30,
			"model": nil, "replay_protected": true, "last_boot": 2, "last_seq": 9, "replay_refused": 4, "health": nil},
		{"id": d4, "name": "twin", "status": "online", "link_state": "online", "last_seen": "2026-11-22T11:59:00Z", "tags": []string{}, "expected_interval_s": 5, "replay_protected": false},
		{"id": d5, "name": "twin", "status": "online", "link_state": "online", "last_seen": "2026-11-22T11:58:00Z", "tags": []string{}, "expected_interval_s": 5, "replay_protected": false},
	}
	f.alerts = []map[string]any{
		{"id": a1, "device_id": d1, "rule_id": "r1", "message": "press-01: temperature above 80 for 30 s", "severity": "critical", "resolved": false, "triggered_at": "2026-11-22T11:50:00+00:00", "resolved_at": nil,
			"category": "machine", "sensor_key": nil, "kind": "rule", "occurrences": 14, "last_value": 83.5, "peak_value": 86.0, "first_seen_at": "2026-11-22T11:49:30+00:00", "last_seen_at": "2026-11-22T11:59:50+00:00", "evidence": nil},
		{"id": a2, "device_id": d1, "message": "press-01: sensor bme280 is not answering (missing)", "severity": "warning", "resolved": false, "triggered_at": "2026-11-22T11:40:00+00:00", "resolved_at": nil,
			"category": "monitoring", "sensor_key": "bme280", "kind": "sensor", "occurrences": 1},
		{"id": a3, "device_id": d2, "message": "pump-02 has not reported for 2 minutes (back online after 7 min 30 s)", "severity": "warning", "resolved": true, "triggered_at": "2026-11-21T08:00:00+00:00", "resolved_at": "2026-11-21T08:07:30+00:00",
			"category": "monitoring", "kind": "offline", "occurrences": 1},
		{"id": a4, "device_id": d2, "message": "pump-02 has not reported for 2 minutes", "severity": "warning", "resolved": false, "triggered_at": "2026-11-20T09:00:00+00:00", "resolved_at": nil,
			"category": "monitoring", "kind": "offline", "occurrences": 1},
	}
	f.tickets = []map[string]any{
		{"id": t1, "device_id": d1, "alert_id": a1, "title": "High temperature on press-01", "description": "Temperature exceeded 80C.", "status": "open", "priority": "critical",
			"assigned_to_name": "Alex", "created_by_name": "Sam", "created_at": "2026-11-22T11:51:00Z", "updated_at": "2026-11-22T11:55:00Z", "ticket_number": 12},
		{"id": t2, "device_id": d2, "alert_id": nil, "title": "Check pump-02 power", "description": nil, "status": "closed", "priority": "low",
			"assigned_to_name": nil, "created_by_name": "Alex", "created_at": "2026-11-10T08:00:00Z", "updated_at": "2026-11-11T08:00:00Z", "ticket_number": 3},
	}
	rows := make([]map[string]any, 0, 30)
	for i := 0; i < 30; i++ {
		at := time.Date(2026, 11, 22, 11, 59, 55, 0, time.UTC).Add(-time.Duration(i) * 5 * time.Second)
		rows = append(rows, map[string]any{"id": fmt.Sprintf("00000000-0000-4000-8000-%012d", 100-i), "device_id": d1, "recorded_at": at.Format(time.RFC3339), "node_type": "esp32",
			"temperature": 24.5 + float64(i)/10, "humidity": 48.0, "pressure": nil, "vibration_x": 0.02, "anomaly_score": nil, "is_anomaly": false})
	}
	f.readings[d1] = rows
}

func (f *fakeAPI) tokenInfo(tok string) (scope string, expires time.Time, id, name string, ok bool) {
	switch tok {
	case tokRead:
		return "read", testNow.Add(90 * 24 * time.Hour), "rd01", "ci script", true
	case tokOperate:
		return "operate", testNow.Add(90 * 24 * time.Hour), "op02", "ops laptop", true
	case tokAdmin:
		return "admin", testNow.Add(90 * 24 * time.Hour), "ad04", "admin laptop", true
	case tokSoon:
		return "read", testNow.Add(5 * 24 * time.Hour), "sn03", "short lived", true
	}
	return "", time.Time{}, "", "", false
}

func first2(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func (f *fakeAPI) isRevoked(tok string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.revoked[tok]
}

func (f *fakeAPI) admin(w http.ResponseWriter, scope string) bool {
	if scope != "admin" {
		writeJSON(w, 403, map[string]any{"code": "scope_too_low", "detail": "This token's scope (" + scope + ") does not allow this. It needs admin"})
		return false
	}
	return true
}

func (f *fakeAPI) total(w http.ResponseWriter, n int) {
	w.Header().Set("X-Total-Count", strconv.Itoa(n))
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func page[T any](items []T, q map[string][]string, offsetName string, defLimit int) []T {
	get := func(name string, def int) int {
		if v := q[name]; len(v) > 0 {
			if n, err := strconv.Atoi(v[0]); err == nil {
				return n
			}
		}
		return def
	}
	off, lim := get(offsetName, get("offset", get("skip", 0))), get("limit", defLimit)
	if off > len(items) {
		off = len(items)
	}
	end := min(off+lim, len(items))
	return items[off:end]
}

func (f *fakeAPI) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	rec := record{Method: r.Method, Path: r.URL.Path, Query: r.URL.RawQuery, Auth: r.Header.Get("Authorization"), Key: r.Header.Get("X-API-Key"), Idem: r.Header.Get("Idempotency-Key")}
	f.records = append(f.records, rec)
	key := r.Method + " " + r.URL.Path
	var scripted *step
	if q := f.script[key]; len(q) > 0 {
		s := q[0]
		if !s.forever {
			f.script[key] = q[1:]
		}
		scripted = &s
	}
	f.mu.Unlock()
	if scripted != nil {
		for k, v := range scripted.header {
			w.Header().Set(k, v)
		}
		if scripted.abort {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(scripted.partial))
			w.(http.Flusher).Flush()
			panic(http.ErrAbortHandler)
		}
		w.WriteHeader(scripted.status)
		_, _ = w.Write([]byte(scripted.body))
		return
	}

	path := r.URL.Path
	if path == "/status" {
		updated := "2026-11-22T11:59:00+00:00"
		if !f.statusTime.IsZero() {
			updated = f.statusTime.UTC().Format(time.RFC3339)
		}
		writeJSON(w, 200, map[string]any{"status": "operational", "api": "ok", "database": "ok", "redis": "ok", "model": "ok", "version": "1.0.0", "updated_at": updated})
		return
	}
	if path == "/openapi.json" {
		writeJSON(w, 200, map[string]any{"info": map[string]any{"title": "PHAEMOS API", "version": "1.0.0"}})
		return
	}
	if path == "/api/v1/telemetry" && r.Method == http.MethodPost {
		if r.Header.Get("X-API-Key") != devKey {
			writeJSON(w, 401, map[string]any{"detail": "Invalid API key"})
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		writeJSON(w, 201, map[string]any{"id": "x", "device_id": d1, "anomaly_score": 0.1, "is_anomaly": false, "boot": body["boot"], "seq": body["seq"], "up": body["up"]})
		return
	}
	if path == "/api/v1/firmware/latest" {
		if r.Header.Get("X-API-Key") != devKey {
			writeJSON(w, 401, map[string]any{"code": "invalid_key", "detail": "Invalid API key"})
			return
		}
		writeJSON(w, 404, map[string]any{"code": "not_found", "detail": "No firmware uploaded"})
		return
	}
	// everything else needs a token
	auth := r.Header.Get("Authorization")
	tok := strings.TrimPrefix(auth, "Bearer ")
	scope, expires, tid, tname, ok := f.tokenInfo(tok)
	if !strings.HasPrefix(auth, "Bearer ") || !ok || f.isRevoked(tok) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeJSON(w, 401, map[string]any{"detail": "Invalid or expired token"})
		return
	}
	if r.Header.Get("X-API-Key") != "" {
		f.t.Errorf("a request carried both a token and a device key")
	}
	switch {
	case path == "/api/v1/auth/whoami":
		writeJSON(w, 200, map[string]any{"id": "u-1", "role": "admin", "signed_in_with": "token",
			"token": map[string]any{"id": tid, "name": tname, "scope": scope, "expires_at": expires.Format(time.RFC3339)}})
	case path == "/api/v1/tokens":
		if r.Method != http.MethodGet {
			writeJSON(w, 403, map[string]any{"detail": "A signed-in session is needed for this. An API token cannot do it"})
			return
		}
		writeJSON(w, 200, []any{map[string]any{"id": tid, "name": tname, "scope": scope, "created_at": "2026-11-01T09:00:00Z", "expires_at": expires.Format(time.RFC3339), "last_used_at": "2026-11-22T11:00:00Z"}})
	case path == "/api/v1/health/summary":
		writeJSON(w, 200, map[string]any{"total_devices": 5, "online": 4, "offline": 1, "link_states": map[string]int{"online": 3, "late": 1, "offline": 1}, "active_alerts": 3, "open_tickets": 1, "health_score": 72})
	case path == "/api/v1/ml/status":
		writeJSON(w, 200, map[string]any{"state": "ok", "trained_at": "2026-11-21T04:10:00+00:00",
			"models":       []any{map[string]any{"key": "machine:" + d1, "scope": "machine", "legacy": false, "false_alerts_per_week": 0.0}, map[string]any{"key": "esp32", "scope": "node_type", "legacy": true, "false_alerts_per_week": 0.4}},
			"last_retrain": map[string]any{"status": "trained", "finished_at": "2026-11-21T04:10:07+00:00", "summary": "Retrain: 3 models accepted", "trigger": "nightly"},
			"schedule":     map[string]any{"nightly_utc": "04:00", "next_at": "2026-11-23T04:00:00+00:00"}})
	case path == "/api/v1/devices":
		items := f.devices
		q := r.URL.Query()
		var kept []map[string]any
		for _, d := range items {
			if s := q.Get("name"); s != "" && !strings.EqualFold(d["name"].(string), s) {
				continue
			}
			if s := q.Get("search"); s != "" && !strings.Contains(strings.ToLower(d["name"].(string)), strings.ToLower(s)) {
				continue
			}
			if s := q.Get("status"); s != "" && d["status"] != s {
				continue
			}
			if s := q.Get("tag"); s != "" {
				found := false
				for _, tg := range d["tags"].([]string) {
					found = found || tg == s
				}
				if !found {
					continue
				}
			}
			kept = append(kept, d)
		}
		f.total(w, len(kept))
		writeJSON(w, 200, page(kept, q, "skip", 20))
	case strings.HasPrefix(path, "/api/v1/devices/") && !strings.HasSuffix(path, "/accept-counter"):
		id := strings.TrimPrefix(path, "/api/v1/devices/")
		for _, d := range f.devices {
			if d["id"] == id {
				writeJSON(w, 200, d)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"detail": "Device not found"})
	case path == "/api/v1/alerts":
		q := r.URL.Query()
		var kept []map[string]any
		for _, a := range f.alerts {
			if dev := q.Get("device_id"); dev != "" && a["device_id"] != dev {
				continue
			}
			if q.Get("resolved") == "false" && a["resolved"] == true {
				continue
			}
			if c := q.Get("category"); c != "" && a["category"] != c {
				continue
			}
			if sv := q.Get("severity"); sv != "" && a["severity"] != sv {
				continue
			}
			if k := q.Get("kind"); k != "" && a["kind"] != k {
				continue
			}
			kept = append(kept, a)
		}
		f.total(w, len(kept))
		writeJSON(w, 200, page(kept, q, "offset", 100))
	case strings.HasPrefix(path, "/api/v1/alerts/") && strings.HasSuffix(path, "/resolve") && (r.Method == http.MethodPost || r.Method == http.MethodPatch):
		if r.Method == http.MethodPatch {
			w.Header().Set("Deprecation", "true")
			w.Header().Set("Sunset", "Wed, 01 Jul 2027 00:00:00 GMT")
		}
		if scope == "read" {
			writeJSON(w, 403, map[string]any{"detail": "This token's scope (read) does not allow this. It needs operate"})
			return
		}
		id := strings.TrimSuffix(strings.TrimPrefix(path, "/api/v1/alerts/"), "/resolve")
		for _, a := range f.alerts {
			if a["id"] == id {
				f.mu.Lock()
				f.resolved[id] = true
				f.mu.Unlock()
				out := map[string]any{}
				for k, v := range a {
					out[k] = v
				}
				out["resolved"] = true
				out["resolved_at"] = "2026-11-22T12:00:00+00:00"
				writeJSON(w, 200, out)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"detail": "Alert not found"})
	case strings.HasPrefix(path, "/api/v1/alerts/"):
		id := strings.TrimPrefix(path, "/api/v1/alerts/")
		for _, a := range f.alerts {
			if a["id"] == id {
				writeJSON(w, 200, a)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"code": "not_found", "detail": "Alert not found"})
	case path == "/api/v1/maintenance-windows" && r.Method == http.MethodGet:
		f.total(w, len(f.windows))
		writeJSON(w, 200, page(f.windows, r.URL.Query(), "offset", 50))
	case path == "/api/v1/maintenance-windows" && r.Method == http.MethodPost:
		if !f.admin(w, scope) {
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		key := r.Header.Get("Idempotency-Key")
		f.mu.Lock()
		f.windowKeys = append(f.windowKeys, key)
		if key != "" {
			if first, ok := f.idempotent[key]; ok {
				f.mu.Unlock()
				w.Header().Set("Idempotent-Replayed", "true")
				writeJSON(w, 201, first)
				return
			}
		}
		body["id"] = fmt.Sprintf("c1000000-0000-4000-8000-%012d", len(f.windows)+1)
		f.windows = append(f.windows, body)
		if key != "" {
			f.idempotent[key] = body
		}
		f.mu.Unlock()
		writeJSON(w, 201, body)
	case strings.HasPrefix(path, "/api/v1/maintenance-windows/") && r.Method == http.MethodPatch:
		if !f.admin(w, scope) {
			return
		}
		id := strings.TrimPrefix(path, "/api/v1/maintenance-windows/")
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		for _, win := range f.windows {
			if win["id"] == id {
				win["end_at"] = body["end_at"]
				writeJSON(w, 200, win)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"code": "not_found", "detail": "Maintenance window not found"})
	case strings.HasSuffix(path, "/accept-counter") && r.Method == http.MethodPost:
		if !f.admin(w, scope) {
			return
		}
		id := strings.TrimSuffix(strings.TrimPrefix(path, "/api/v1/devices/"), "/accept-counter")
		for _, d := range f.devices {
			if d["id"] == id {
				out := map[string]any{}
				for k, v := range d {
					out[k] = v
				}
				out["replay_refused"] = 0
				out["replay_recovery"] = "The counter was accepted. Rotate this device's key as well if the counter had been pushed up."
				writeJSON(w, 200, out)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"code": "not_found", "detail": "Device not found"})
	case path == "/api/v1/tokens/current" && r.Method == http.MethodDelete:
		f.mu.Lock()
		f.revoked[tok] = true
		f.mu.Unlock()
		w.WriteHeader(204)
	case path == "/api/v1/tickets":
		q := r.URL.Query()
		var kept []map[string]any
		for _, tk := range f.tickets {
			if s := q.Get("status"); s != "" && tk["status"] != s {
				continue
			}
			if s := q.Get("priority"); s != "" && tk["priority"] != s {
				continue
			}
			if s := q.Get("device_id"); s != "" && tk["device_id"] != s {
				continue
			}
			if s := q.Get("ticket_number"); s != "" && fmt.Sprint(tk["ticket_number"]) != s {
				continue
			}
			kept = append(kept, tk)
		}
		f.total(w, len(kept))
		writeJSON(w, 200, page(kept, q, "skip", 20))
	case strings.HasPrefix(path, "/api/v1/tickets/"):
		id := strings.TrimPrefix(path, "/api/v1/tickets/")
		for _, tk := range f.tickets {
			if tk["id"] == id {
				writeJSON(w, 200, tk)
				return
			}
		}
		writeJSON(w, 404, map[string]any{"detail": "Ticket not found"})
	case path == "/api/v1/telemetry/export":
		f.export(w, r)
	case strings.HasPrefix(path, "/api/v1/telemetry/") && strings.HasSuffix(path, "/latest"):
		id := strings.TrimSuffix(strings.TrimPrefix(path, "/api/v1/telemetry/"), "/latest")
		if rows := f.readings[id]; len(rows) > 0 {
			writeJSON(w, 200, rows[0])
			return
		}
		writeJSON(w, 404, map[string]any{"detail": "No telemetry found for device"})
	case strings.HasPrefix(path, "/api/v1/telemetry/"):
		if f.onReadings != nil {
			f.onReadings()
		}
		id := strings.TrimPrefix(path, "/api/v1/telemetry/")
		q := r.URL.Query()
		rows := f.readings[id]
		var kept []map[string]any
		for _, row := range rows {
			from := first2(q.Get("from"), q.Get("from_ts"))
			if from != "" {
				ft, _ := time.Parse(time.RFC3339Nano, from)
				rt, _ := time.Parse(time.RFC3339, row["recorded_at"].(string))
				if rt.Before(ft) {
					continue
				}
			}
			kept = append(kept, row)
		}
		// keyset: before=<time>,<id> returns the rows after that one in the same (newest first) order
		start := 0
		if before := q.Get("before"); before != "" {
			parts := strings.SplitN(before, ",", 2)
			for i, row := range kept {
				if row["id"] == parts[len(parts)-1] {
					start = i + 1
				}
			}
		} else if off, err := strconv.Atoi(q.Get("offset")); err == nil {
			start = min(off, len(kept))
		}
		limit := 100
		if l, err := strconv.Atoi(q.Get("limit")); err == nil {
			limit = l
		}
		end := min(start+limit, len(kept))
		out := kept[start:end]
		if len(out) == limit && end < len(kept) {
			last := out[len(out)-1]
			w.Header().Set("X-Next-Before", fmt.Sprint(last["recorded_at"], ",", last["id"]))
		}
		writeJSON(w, 200, out)
	default:
		writeJSON(w, 404, map[string]any{"detail": "Not Found"})
	}
}

func (f *fakeAPI) export(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if q.Get("device_id") == "" || q.Get("from_ts") == "" {
		writeJSON(w, 422, map[string]any{"detail": "from_ts is required: an export covers at most 31 days"})
		return
	}
	w.Header().Set("Content-Type", "text/csv")
	w.Header().Set("Content-Disposition", "attachment; filename=telemetry.csv")
	rows := f.exportRows
	if rows == 0 {
		rows = 3
	}
	fmt.Fprintln(w, "id,device_id,recorded_at,temperature")
	for i := 0; i < rows; i++ {
		fmt.Fprintf(w, "%d,%s,2026-11-22T11:00:%02dZ,24.%d\n", i, q.Get("device_id"), i%60, i%10)
	}
}

func (f *fakeAPI) requests() []record {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]record(nil), f.records...)
}

func (f *fakeAPI) count(method, path string) int {
	n := 0
	for _, r := range f.requests() {
		if r.Method == method && r.Path == path {
			n++
		}
	}
	return n
}

func (f *fakeAPI) queue(method, path string, steps ...step) {
	f.mu.Lock()
	f.script[method+" "+path] = steps
	f.mu.Unlock()
}

// ---- running the tool ----

type fakeClock struct {
	mu     sync.Mutex
	now    time.Time
	sleeps []time.Duration
	// onSleep runs after each sleep is recorded
	onSleep func(n int)
}

func (c *fakeClock) Now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.now }

func (c *fakeClock) Sleep(ctx context.Context, d time.Duration) error {
	c.mu.Lock()
	c.sleeps = append(c.sleeps, d)
	c.now = c.now.Add(d)
	n := len(c.sleeps)
	hook := c.onSleep
	c.mu.Unlock()
	if hook != nil {
		hook(n)
	}
	return ctx.Err()
}

func (c *fakeClock) slept() []time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]time.Duration(nil), c.sleeps...)
}

type env struct {
	t      *testing.T
	f      *fakeAPI
	vars   map[string]string
	clock  *fakeClock
	stdin  string
	inTTY  bool
	outTTY bool
	secret func(string) (string, error)
	ctx    context.Context
	dir    string
}

func newEnv(t *testing.T, f *fakeAPI) *env {
	dir := t.TempDir()
	cfgDir := filepath.Join(dir, "cfg")
	e := &env{t: t, f: f, clock: &fakeClock{now: testNow}, ctx: context.Background(), dir: dir, vars: map[string]string{
		"PHAEMOS_CONFIG": filepath.Join(cfgDir, "config"), "PHAEMOS_URL": f.srv.URL, "PHAEMOS_TOKEN": tokRead,
		"PHAEMOS_STATE_DIR": filepath.Join(dir, "state"), "HOME": dir,
	}}
	return e
}

func (e *env) run(args ...string) (stdout, stderr string, code int) {
	var out, errb bytes.Buffer
	bst := time.FixedZone("BST", 3600)
	io := IO{
		In: strings.NewReader(e.stdin), Out: &out, Err: &errb, InTTY: e.inTTY, OutTTY: e.outTTY,
		Getenv: func(k string) string { return e.vars[k] }, ReadSecret: e.secret,
		Clock: e.clock, Now: e.clock.Now, Loc: bst, HTTP: e.f.srv.Client(), Version: "9.9.9-test",
	}
	code = Run(e.ctx, args, io)
	return out.String(), errb.String(), code
}

func (e *env) configPath() string { return e.vars["PHAEMOS_CONFIG"] }

// golden compares output with testdata/<name>.golden.
func golden(t *testing.T, name, got string) {
	t.Helper()
	path := filepath.Join("testdata", name+".golden")
	if *update {
		if err := os.MkdirAll("testdata", 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(got), 0o644); err != nil {
			t.Fatal(err)
		}
		return
	}
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("missing golden file %s: run go test -update. Output was:\n%s", path, got)
	}
	if string(want) != got {
		t.Fatalf("output differs from %s.\nwant:\n%s\ngot:\n%s", path, want, got)
	}
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

var _ = api.DefaultRetry
