package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

func mustOK(t *testing.T, e *env, args ...string) string {
	t.Helper()
	out, errs, code := e.run(args...)
	if code != 0 {
		t.Fatalf("%v: exit %d\nstdout: %s\nstderr: %s", args, code, out, errs)
	}
	return out
}

// every command's table (to a pipe, so tab-separated), its aligned form on a terminal and its JSON
func TestCommandOutputGolden(t *testing.T) {
	f := newFake(t)
	cases := []struct {
		name string
		args []string
		tty  bool
	}{
		{"status_table", []string{"status"}, false},
		{"status_tty", []string{"status"}, true},
		{"status_json", []string{"status", "-o", "json"}, false},
		{"health_table", []string{"health"}, false},
		{"health_tty", []string{"health"}, true},
		{"health_json", []string{"health", "-o", "json"}, false},
		{"model_table", []string{"model", "status"}, false},
		{"model_json", []string{"model", "status", "-o", "json"}, false},
		{"machines_list_table", []string{"devices", "list"}, false},
		{"machines_list_tty", []string{"devices", "list"}, true},
		{"machines_list_wide", []string{"devices", "list", "--wide"}, false},
		{"machines_list_json", []string{"devices", "list", "-o", "json"}, false},
		{"machines_list_jsonl", []string{"devices", "list", "-o", "jsonl"}, false},
		{"machines_show_table", []string{"devices", "show", "press-01"}, false},
		{"machines_show_tty", []string{"devices", "show", "press-01"}, true},
		{"machines_show_offline", []string{"devices", "show", "pump-02"}, false},
		{"machines_show_json", []string{"devices", "show", "press-01", "-o", "json"}, false},
		{"readings_latest_table", []string{"readings", "latest", "press-01"}, false},
		{"readings_latest_json", []string{"readings", "latest", "press-01", "-o", "json"}, false},
		{"readings_latest_count_table", []string{"readings", "latest", "press-01", "--count", "3"}, false},
		{"readings_latest_count_jsonl", []string{"readings", "latest", "press-01", "--count", "2", "-o", "jsonl"}, false},
		{"alerts_list_table", []string{"alerts", "list"}, false},
		{"alerts_list_open_tty", []string{"alerts", "list", "--open"}, true},
		{"alerts_list_open_critical_json", []string{"alerts", "list", "--open", "--severity", "critical", "-o", "json"}, false},
		{"alerts_list_machine_table", []string{"alerts", "list", "--machine", "pump-02", "--open"}, false},
		{"alerts_show_table", []string{"alerts", "show", a1}, false},
		{"alerts_show_json", []string{"alerts", "show", a1, "-o", "json"}, false},
		{"tickets_list_table", []string{"tickets", "list"}, false},
		{"tickets_list_tty", []string{"tickets", "list"}, true},
		{"tickets_list_json", []string{"tickets", "list", "-o", "json"}, false},
		{"tickets_show_table", []string{"tickets", "show", "PHM-0012"}, false},
		{"tickets_show_json", []string{"tickets", "show", t1, "-o", "json"}, false},
		{"version_table", []string{"version", "--server"}, false},
		{"version_json", []string{"version", "--server", "-o", "json"}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			e := newEnv(t, f)
			e.outTTY = c.tty
			e.vars["TERM"] = "xterm"
			e.vars["NO_COLOR"] = "1" // goldens hold no escape codes: colour has its own test
			out, errs, code := e.run(c.args...)
			if code != 0 {
				t.Fatalf("exit %d: %s", code, errs)
			}
			golden(t, c.name, strings.ReplaceAll(out, f.srv.URL, "http://api.test"))
		})
	}
}

// the JSON of a read command is the server's own, byte for byte once compacted
func TestJSONOutputIsTheServersOwnDocument(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	out := mustOK(t, e, "health", "-o", "json")
	var got, want any
	if err := json.Unmarshal([]byte(out), &got); err != nil {
		t.Fatalf("not one JSON document: %v\n%s", err, out)
	}
	if strings.Count(strings.TrimSpace(out), "\n") != 0 {
		t.Fatalf("not on one line: %q", out)
	}
	_ = json.Unmarshal([]byte(`{"total_devices":5,"online":4,"offline":1,"link_states":{"online":3,"late":1,"offline":1},"active_alerts":3,"open_tickets":1,"health_score":72}`), &want)
	g, _ := json.Marshal(got)
	w, _ := json.Marshal(want)
	if string(g) != string(w) {
		t.Fatalf("got %s want %s", g, w)
	}
	list := mustOK(t, e, "devices", "list", "-o", "json")
	var arr []map[string]any
	if err := json.Unmarshal([]byte(list), &arr); err != nil || len(arr) != 5 {
		t.Fatalf("machines list json: %v %d", err, len(arr))
	}
	lines := strings.Split(strings.TrimSpace(mustOK(t, e, "devices", "list", "-o", "jsonl")), "\n")
	if len(lines) != 5 {
		t.Fatalf("jsonl lines: %d", len(lines))
	}
	for _, l := range lines {
		var one map[string]any
		if err := json.Unmarshal([]byte(l), &one); err != nil {
			t.Fatalf("bad jsonl line %q", l)
		}
	}
}

func TestMachinesFiltersAndNameLookup(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	if out := mustOK(t, e, "devices", "list", "--status", "offline"); !strings.Contains(out, "pump-02") || strings.Contains(out, "press-01") {
		t.Fatalf("status filter: %s", out)
	}
	if out := mustOK(t, e, "devices", "list", "--tag", "spare"); !strings.Contains(out, "Press-01b") || strings.Contains(out, "pump-02") {
		t.Fatalf("tag filter: %s", out)
	}
	if out := mustOK(t, e, "devices", "list", "--search", "twin"); strings.Count(out, "twin") != 2 {
		t.Fatalf("search: %s", out)
	}
	// a name matches exactly, ignoring case and not as a substring
	if out := mustOK(t, e, "devices", "show", "PRESS-01", "-o", "json"); !strings.Contains(out, d1) || strings.Contains(out, d3) {
		t.Fatalf("name lookup: %s", out)
	}
	if _, errs, code := e.run("devices", "show", "press"); code != ExitNotFound || !strings.Contains(errs, `no device is called "press". Did you mean: press-01, Press-01b`) {
		t.Fatalf("partial name: %d %s", code, errs)
	}
	if _, errs, code := e.run("devices", "show", "twin"); code != ExitConflict || !strings.Contains(errs, "use the id") {
		t.Fatalf("ambiguous: %d %s", code, errs)
	}
	if _, _, code := e.run("devices", "show", d2); code != 0 {
		t.Fatalf("by id: %d", code)
	}
	if _, errs, code := e.run("devices", "show", "99999999-9999-4999-8999-999999999999"); code != ExitNotFound || !strings.Contains(errs, "Device not found") {
		t.Fatalf("unknown id: %d %s", code, errs)
	}
}

func TestAlertFiltersAndLookup(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	open := mustOK(t, e, "alerts", "list", "--open", "-o", "json")
	var alerts []map[string]any
	_ = json.Unmarshal([]byte(open), &alerts)
	if len(alerts) != 3 {
		t.Fatalf("open: %d", len(alerts))
	}
	// the severity filter is the tool's own
	crit := mustOK(t, e, "alerts", "list", "--severity", "CRITICAL", "-o", "json")
	_ = json.Unmarshal([]byte(crit), &alerts)
	if len(alerts) != 1 || alerts[0]["id"] != a1 {
		t.Fatalf("severity: %v", alerts)
	}
	mon := mustOK(t, e, "alerts", "list", "--category", "monitoring", "--open", "-o", "json")
	_ = json.Unmarshal([]byte(mon), &alerts)
	if len(alerts) != 2 {
		t.Fatalf("category: %d", len(alerts))
	}
	// the per-machine route has no resolved filter: --open is applied to what was read
	m := mustOK(t, e, "alerts", "list", "--machine", "pump-02", "--open", "-o", "json")
	_ = json.Unmarshal([]byte(m), &alerts)
	if len(alerts) != 1 || alerts[0]["id"] != a4 {
		t.Fatalf("machine+open: %v", alerts)
	}
	if _, errs, code := e.run("alerts", "show", "a9000000-0000-4000-8000-000000000009"); code != ExitNotFound || !strings.Contains(errs, "Alert not found") {
		t.Fatalf("missing alert: %d %s", code, errs)
	}
	if _, errs, code := e.run("alerts", "show", "nonsense"); code != ExitUsage {
		t.Fatalf("bad id: %d %s", code, errs)
	}
	if _, errs, code := e.run("alerts", "list", "--category", "nope"); code != ExitUsage {
		t.Fatalf("bad category: %d %s", code, errs)
	}
}

func TestTicketLookupByNumberAndFilters(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for _, ref := range []string{"PHM-0012", "phm-12", "12"} {
		if out := mustOK(t, e, "tickets", "show", ref, "-o", "json"); !strings.Contains(out, t1) {
			t.Fatalf("%s: %s", ref, out)
		}
	}
	if _, errs, code := e.run("tickets", "show", "PHM-0999"); code != ExitNotFound || !strings.Contains(errs, "PHM-0999") {
		t.Fatalf("missing: %d %s", code, errs)
	}
	if _, _, code := e.run("tickets", "show", "banana"); code != ExitUsage {
		t.Fatal("bad ref should be a usage error")
	}
	if out := mustOK(t, e, "tickets", "list", "--status", "closed"); !strings.Contains(out, "PHM-0003") || strings.Contains(out, "PHM-0012") {
		t.Fatalf("status: %s", out)
	}
	if out := mustOK(t, e, "tickets", "list", "--machine", "press-01"); !strings.Contains(out, "PHM-0012") || strings.Contains(out, "PHM-0003") {
		t.Fatalf("machine filter is the tool's own: %s", out)
	}
}

func TestSendLoadAndStatusWithoutToken(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	out := mustOK(t, e, "send", "--json", `{"device_id":"d1","temperature":24.1}`)
	if !strings.Contains(out, `"seq": 0`) || !strings.Contains(out, `"boot"`) || !strings.Contains(out, `"up"`) {
		t.Fatalf("send did not stamp boot, seq and up:\n%s", out)
	}
	last := f.requests()[len(f.requests())-1]
	if last.Key != devKey || last.Auth != "" {
		t.Fatalf("a device post must send the key and no token: %+v", last)
	}
	if out := mustOK(t, e, "dev", "load", "--requests", "5"); !strings.Contains(out, "5 requests: 5 accepted, 0 throttled (429), 0 failed") {
		t.Fatalf("load: %s", out)
	}
	// status works with no token
	if out := mustOK(t, e, "status"); strings.Contains(out, "signed in") {
		t.Fatalf("status without a token: %s", out)
	}
	if _, _, code := e.run("load"); code != 0 {
		// the key is in the environment, so this runs
		t.Fatalf("load with env key: %d", code)
	}
	delete(e.vars, "PHAEMOS_DEVICE_KEY")
	if _, errs, code := e.run("load"); code != ExitUsage || !strings.Contains(errs, "device key") {
		t.Fatalf("load without a key: %d %s", code, errs)
	}
}

func TestSendIsNeverRetried(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	f.queue("POST", "/api/v1/telemetry", step{status: 503, forever: true})
	_, errs, code := e.run("send", "--json", `{"device_id":"d1"}`)
	if code != ExitUnavailable {
		t.Fatalf("exit %d: %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/telemetry"); n != 1 {
		t.Fatalf("a device post was sent %d times", n)
	}
	if len(e.clock.slept()) != 0 {
		t.Fatalf("a device post waited: %v", e.clock.slept())
	}
}

func TestVersionShowsServerWhenPublishedAndReachability(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	out := mustOK(t, e, "version", "--server")
	if !strings.Contains(out, "9.9.9-test") || !strings.Contains(out, "1.0.0") {
		t.Fatalf("%s", out)
	}
	f.queue("GET", "/openapi.json", step{status: 404, body: `{"detail":"Not Found"}`, forever: true})
	if out := mustOK(t, e, "version", "--server"); !strings.Contains(out, "not published by this server") {
		t.Fatalf("%s", out)
	}
	e.vars["PHAEMOS_URL"] = "http://127.0.0.1:1"
	out, _, code := e.run("version", "--server")
	if code != 0 || !strings.Contains(out, "not reachable") {
		t.Fatalf("an unreachable server must not fail version: %d %s", code, out)
	}
}

func TestStatusShowsWhoAndWarnsBeforeExpiry(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	out := mustOK(t, e, "status")
	for _, want := range []string{"signed in as", "admin", "ci script", "read"} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %q in:\n%s", want, out)
		}
	}
	e.vars["PHAEMOS_TOKEN"] = tokSoon
	out, errs, code := e.run("auth", "status")
	if code != 0 || !strings.Contains(errs, "expires in 5 days") || !strings.Contains(out, "(in 5 days)") {
		t.Fatalf("expiry warning: %d\n%s\n%s", code, out, errs)
	}
	e.vars["PHAEMOS_TOKEN"] = tokRead
	if _, errs, _ := e.run("auth", "status"); strings.Contains(errs, "expires in") {
		t.Fatalf("a token with 90 days left must not warn: %s", errs)
	}
}
