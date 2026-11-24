package cli

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestOldNamesStillWorkAndMachinesIsDevices(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	a := mustOK(t, e, "machines", "list", "-o", "json")
	b := mustOK(t, e, "devices", "list", "-o", "json")
	if a != b {
		t.Fatal("machines must be the same command as devices")
	}
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	out := mustOK(t, e, "send", "--json", `{"device_id":"d1"}`)
	out2 := mustOK(t, e, "dev", "send", "--json", `{"device_id":"d1"}`)
	if !strings.Contains(out, `"seq": 0`) || !strings.Contains(out2, `"seq": 0`) {
		t.Fatalf("send and dev send are one command:\n%s\n%s", out, out2)
	}
	if out := mustOK(t, e, "load", "--requests", "2"); !strings.Contains(out, "2 accepted") {
		t.Fatalf("load: %s", out)
	}
	// the help lists the new names only
	top := mustOK(t, e, "help")
	for _, gone := range []string{"machines list", "  send ", "  load "} {
		if strings.Contains(top, gone) {
			t.Fatalf("the help still lists %q:\n%s", gone, top)
		}
	}
	for _, want := range []string{"devices list", "dev send", "dev load", "doctor", "windows start", "tokens revoke-current", "devices accept-counter"} {
		if !strings.Contains(top, want) {
			t.Fatalf("the help lacks %q", want)
		}
	}
	if strings.Contains(mustOK(t, e, "help", "devices"), "rotate") && !strings.Contains(mustOK(t, e, "help", "devices", "accept-counter"), "never rotate") && !strings.Contains(mustOK(t, e, "help", "devices", "accept-counter"), "can never rotate") {
		t.Fatal("the help must say a token cannot rotate a key")
	}
}

func TestDeviceKeyVariableAndTheOldNameWithANotice(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	_, errs, code := e.run("dev", "send", "--json", `{"device_id":"d1"}`)
	if code != 0 || strings.Contains(errs, "old name") {
		t.Fatalf("%d %s", code, errs)
	}
	delete(e.vars, "PHAEMOS_DEVICE_KEY")
	e.vars["PHAEMOS_API_KEY"] = devKey
	_, errs, code = e.run("dev", "send", "--json", `{"device_id":"d1"}`)
	if code != 0 || strings.Count(errs, "PHAEMOS_API_KEY is the old name: use PHAEMOS_DEVICE_KEY") != 1 {
		t.Fatalf("%d %s", code, errs)
	}
	// the new name wins when both are set
	e.vars["PHAEMOS_DEVICE_KEY"] = "wrong-key"
	if _, _, code := e.run("dev", "send", "--json", `{"device_id":"d1"}`); code != ExitNotSignedIn {
		t.Fatalf("PHAEMOS_DEVICE_KEY must win: %d", code)
	}
	// the key never shows in help or in an error
	for _, args := range [][]string{{"dev", "send", "-h"}, {"dev", "load", "--nope"}, {"dev", "send", "--json", "{"}} {
		out, errs, _ := e.run(args...)
		if strings.Contains(out+errs, "wrong-key") || strings.Contains(out+errs, devKey) {
			t.Fatalf("%v leaked the key", args)
		}
	}
}

func TestVersionIsLocalByDefaultAndAsAFlag(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	n := len(f.requests())
	for _, args := range [][]string{{"--version"}, {"version"}, {"version", "-o", "json"}} {
		out := mustOK(t, e, args...)
		if !strings.Contains(out, "9.9.9-test") {
			t.Fatalf("%v: %s", args, out)
		}
	}
	if len(f.requests()) != n {
		t.Fatal("version asked the server without --server")
	}
	// it works with no config and a broken one
	e.vars["PHAEMOS_CONFIG"] = "/nonexistent/dir/config"
	delete(e.vars, "PHAEMOS_URL")
	if _, _, code := e.run("--version"); code != 0 {
		t.Fatal("--version must not need a profile")
	}
	if out := mustOK(t, e, "version", "--server", "--url", f.srv.URL); !strings.Contains(out, "1.0.0") {
		t.Fatalf("--server: %s", out)
	}
}

func TestDoctorEveryCheckAndTheFirstFailingCode(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	e.vars["PHAEMOS_URL"] = f.srv.URL
	f.statusTime = time.Now() // the server's clock is the real time
	e.clock.now = time.Now()
	e.vars["PHAEMOS_TOKEN"] = tokRead
	out, errs, code := e.run("doctor", "-o", "json")
	if code != 0 {
		t.Fatalf("all well: %d %s %s", code, out, errs)
	}
	var report struct {
		OK     bool    `json:"ok"`
		Checks []check `json:"checks"`
	}
	if err := json.Unmarshal([]byte(out), &report); err != nil || !report.OK {
		t.Fatalf("%v %s", err, out)
	}
	names := map[string]string{}
	for _, c := range report.Checks {
		names[c.Name] = c.Status
	}
	for _, want := range []string{"config file", "address and profile", "transport", "server reachable", "clock", "API token", "token can read", "device key"} {
		if _, ok := names[want]; !ok {
			t.Fatalf("no %q check in %v", want, names)
		}
	}
	// a token that is refused: exit 3 and every other check still ran
	e.vars["PHAEMOS_TOKEN"] = tokBad
	out, errs, code = e.run("doctor")
	if code != ExitNotSignedIn || !strings.Contains(out, "fail") || !strings.Contains(out, "device key") || errs != "" && strings.Contains(errs, "pht_") {
		t.Fatalf("%d\n%s\n%s", code, out, errs)
	}
	// no token
	delete(e.vars, "PHAEMOS_TOKEN")
	if _, _, code := e.run("doctor"); code != ExitNotSignedIn {
		t.Fatalf("no token: %d", code)
	}
	// a device key that is refused
	e.vars["PHAEMOS_TOKEN"] = tokRead
	e.vars["PHAEMOS_DEVICE_KEY"] = "wrong"
	if out, _, code := e.run("doctor"); code != ExitNotSignedIn || !strings.Contains(out, "refused the device key") {
		t.Fatalf("%d %s", code, out)
	}
	delete(e.vars, "PHAEMOS_DEVICE_KEY")
	// a clock far out
	e.clock.now = time.Now().Add(2 * time.Hour)
	out, _, code = e.run("doctor")
	if code != ExitFailure || !strings.Contains(out, "clock differs") {
		t.Fatalf("clock: %d %s", code, out)
	}
	e.clock.now = time.Now().Add(2 * time.Minute)
	if out, _, code := e.run("doctor"); code != 0 || !strings.Contains(out, "warn") {
		t.Fatalf("a small clock difference warns and passes: %d %s", code, out)
	}
	// a server that cannot be reached: exit 8, the later checks that need it are skipped or fail
	e.clock.now = time.Now()
	e.vars["PHAEMOS_URL"] = "http://127.0.0.1:1"
	if out, _, code := e.run("doctor"); code != ExitUnavailable || !strings.Contains(out, "skip") {
		t.Fatalf("%d %s", code, out)
	}
	// a bad address: exit 2
	e.vars["PHAEMOS_URL"] = "http://api.example.org"
	if _, _, code := e.run("doctor"); code != ExitUsage {
		t.Fatalf("plain http to a remote host: %d", code)
	}
	// a bad config file is reported and not fatal to the run
	e.vars["PHAEMOS_URL"] = f.srv.URL
	_ = os.MkdirAll(e.dir+"/cfg", 0o700)
	_ = os.WriteFile(e.configPath(), []byte("[x]\n"), 0o644)
	if out, _, code := e.run("doctor"); code != ExitUsage || !strings.Contains(out, "other users can read it") || !strings.Contains(out, "server reachable") {
		t.Fatalf("%d %s", code, out)
	}
}

func TestDoctorNeverShowsTheTokenOrKey(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	for _, tok := range []string{tokRead, tokBad, tokOperate} {
		e.vars["PHAEMOS_TOKEN"] = tok
		out, errs, _ := e.run("doctor", "--verbose")
		if strings.Contains(out+errs, tok) || strings.Contains(out+errs, devKey) {
			t.Fatalf("leak:\n%s\n%s", out, errs)
		}
	}
}

func TestAcceptCounterNeedsAdminConfirmationAndPassesOnTheAdvice(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	_, errs, code := e.run("devices", "accept-counter", "press-01", "--yes")
	if code != ExitForbidden || !strings.Contains(errs, "needs admin") || !strings.Contains(errs, "this command needs the admin scope") {
		t.Fatalf("scope: %d %s", code, errs)
	}
	posts := func() int { return f.count("POST", "/api/v1/devices/"+d1+"/accept-counter") }
	e.vars["PHAEMOS_TOKEN"] = tokAdmin
	base := posts()
	// no terminal, no --yes: refuses, sends nothing
	_, errs, code = e.run("devices", "accept-counter", "press-01")
	if code != ExitUsage || posts() != base {
		t.Fatalf("%d %s", code, errs)
	}
	// a terminal shows the explanation in the question
	e.inTTY = true
	e.stdin = "n\n"
	_, errs, code = e.run("devices", "accept-counter", "press-01")
	for _, want := range []string{"forgotten", "after its flash was wiped", "boot 7, seq 1042"} {
		if !strings.Contains(errs, want) {
			t.Fatalf("the question lacks %q: %s", want, errs)
		}
	}
	if code != ExitFailure || posts() != base {
		t.Fatalf("declined: %d", code)
	}
	e.stdin = "yes\n"
	_, errs, code = e.run("devices", "accept-counter", "press-01")
	if code != 0 || !strings.Contains(errs, "The API advises: The counter was accepted. Rotate this device's key as well") {
		t.Fatalf("%d %s", code, errs)
	}
	// repeating is safe: a 503 is retried
	e.inTTY = false
	before := posts()
	f.queue("POST", "/api/v1/devices/"+d1+"/accept-counter", step{status: 503})
	if _, _, code := e.run("devices", "accept-counter", "press-01", "--yes"); code != 0 || posts()-before != 2 {
		t.Fatalf("%d %d", code, posts()-before)
	}
	// there is no command that rotates a key and the help says why
	if _, errs, code := e.run("devices", "rotate-key", "press-01"); code != ExitUsage || !strings.Contains(errs, "unknown command") {
		t.Fatalf("%d %s", code, errs)
	}
	help := mustOK(t, e, "help", "devices", "accept-counter")
	if !strings.Contains(help, "a token can never rotate a key") {
		t.Fatalf("the help must say a token cannot rotate a key:\n%s", help)
	}
}

func TestMaintenanceWindows(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokAdmin
	if _, errs, code := e.run("windows", "start", "press-01", "--for", "2h"); code != ExitUsage {
		t.Fatalf("no --yes and no terminal: %d %s", code, errs)
	}
	_, errs, code := e.run("windows", "start", "press-01", "--for", "2h", "--label", "bearing swap", "--yes")
	if code != 0 || !strings.Contains(errs, "silenced until 2026-11-22 15:00:00 BST") {
		t.Fatalf("%d %s", code, errs)
	}
	last := f.windows[len(f.windows)-1]
	if last["label"] != "bearing swap" || last["device_id"] != d1 || last["suppress_alerts"] != true || last["start_at"] != "2026-11-22T12:00:00Z" || last["end_at"] != "2026-11-22T14:00:00Z" {
		t.Fatalf("%v", last)
	}
	out := mustOK(t, e, "windows", "list")
	if !strings.Contains(out, "bearing swap") || !strings.Contains(out, "press-01") || !strings.Contains(out, "active") {
		t.Fatalf("%s", out)
	}
	if out := mustOK(t, e, "windows", "list", "-o", "json"); !strings.Contains(out, "bearing swap") {
		t.Fatal(out)
	}
	// end it
	mustOK(t, e, "windows", "end", "c1000000-0000-4000-8000-000000000001")
	if f.windows[len(f.windows)-1]["end_at"] != "2026-11-22T12:00:00Z" {
		t.Fatalf("not ended: %v", f.windows[len(f.windows)-1])
	}
	if out := mustOK(t, e, "windows", "list"); !strings.Contains(out, "ended") {
		t.Fatalf("%s", out)
	}
	for name, args := range map[string][]string{
		"no --for":  {"windows", "start", "press-01", "--yes"},
		"too long":  {"windows", "start", "press-01", "--for", "800h", "--yes"},
		"bad id":    {"windows", "end", "nope"},
		"no device": {"windows", "start", "--for", "1h", "--yes"},
	} {
		if _, _, code := e.run(args...); code != ExitUsage {
			t.Fatalf("%s: %d", name, code)
		}
	}
	// a token that may not do it
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	if _, errs, code := e.run("windows", "start", "press-01", "--for", "1h", "--yes"); code != ExitForbidden || !strings.Contains(errs, "needs the admin scope") {
		t.Fatalf("%d %s", code, errs)
	}
	if _, _, code := e.run("windows", "list"); code != 0 {
		t.Fatal("a read token lists windows")
	}
}

func TestTokensListAndRevokeCurrent(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	e.stdin = tokRead + "\n"
	mustOK(t, e, "auth", "login")
	out := mustOK(t, e, "tokens", "list")
	if !strings.Contains(out, "ci script") || !strings.Contains(out, "*") || strings.Contains(out, "READSECRET") {
		t.Fatalf("%s", out)
	}
	if j := mustOK(t, e, "tokens", "list", "-o", "json"); !strings.Contains(j, `"last_used_at"`) {
		t.Fatalf("%s", j)
	}
	if _, errs, code := e.run("tokens", "revoke-current"); code != ExitUsage || !strings.Contains(errs, "--yes") {
		t.Fatalf("%d %s", code, errs)
	}
	_, errs, code := e.run("tokens", "revoke-current", "--yes")
	if code != 0 || !strings.Contains(errs, "removed from the config file") {
		t.Fatalf("%d %s", code, errs)
	}
	data, _ := os.ReadFile(e.configPath())
	if strings.Contains(string(data), "pht_") {
		t.Fatalf("the revoked token is still in the file:\n%s", data)
	}
	// the server now refuses it
	e.vars["PHAEMOS_TOKEN"] = tokRead
	if _, _, code := e.run("health"); code != ExitNotSignedIn {
		t.Fatalf("a revoked token must be refused: %d", code)
	}
	if f.count("DELETE", "/api/v1/tokens/current") != 1 {
		t.Fatal("one revoke call")
	}
	// there is no command to revoke another token or make one
	for _, args := range [][]string{{"tokens", "revoke", "x"}, {"tokens", "create"}} {
		if _, _, code := e.run(args...); code != ExitUsage {
			t.Fatalf("%v: %d", args, code)
		}
	}
}

func TestLoadRefusesANonLocalServerAndReportsThrottlingApart(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	e.vars["PHAEMOS_URL"] = "https://api.example.org"
	_, errs, code := e.run("dev", "load")
	if code != ExitUsage || !strings.Contains(errs, "--yes-this-is-not-production") {
		t.Fatalf("%d %s", code, errs)
	}
	if len(f.requests()) != 0 {
		t.Fatal("a refused load sent something")
	}
	e.vars["PHAEMOS_URL"] = f.srv.URL
	// the default rate is below the allowance and is paced on the clock
	mustOK(t, e, "dev", "load", "--requests", "4")
	sleeps := e.clock.slept()
	if len(sleeps) != 3 || sleeps[0] != 2*time.Second {
		t.Fatalf("30 a minute is a post every 2 s: %v", sleeps)
	}
	// 429s are counted apart, left out of the latency and give exit 7
	f.queue("POST", "/api/v1/telemetry", step{status: 429, header: map[string]string{"Retry-After": "1"}, forever: true})
	out, errs, code := e.run("dev", "load", "--requests", "5", "--rate", "100")
	if code != ExitRateLimited || !strings.Contains(out, "0 accepted, 5 throttled (429), 0 failed") || !strings.Contains(errs, "above the 60 a minute") {
		t.Fatalf("%d\n%s\n%s", code, out, errs)
	}
	f.queue("POST", "/api/v1/telemetry", step{status: 500, forever: true})
	out, _, code = e.run("dev", "load", "--requests", "3", "-o", "json")
	var body map[string]any
	_ = json.Unmarshal([]byte(out), &body)
	if code != ExitUnavailable || body["failed"] != float64(3) || body["throttled"] != float64(0) {
		t.Fatalf("%d %s", code, out)
	}
	// a non-local server is allowed with the flag
	e.vars["PHAEMOS_URL"] = "https://api.example.org"
	if _, errs, _ := e.run("dev", "load", "--requests", "1", "--yes-this-is-not-production"); strings.Contains(errs, "not a local server") {
		t.Fatal("the flag must allow it")
	}
	help := mustOK(t, e, "help", "dev", "load")
	for _, want := range []string{"not the limiter", "60 posts a minute", "counted apart", "exits 8"} {
		if !strings.Contains(strings.Join(strings.Fields(help), " "), want) {
			t.Fatalf("the help lacks %q:\n%s", want, help)
		}
	}
}

func TestAlertsAreFilteredByTheServerAndReadByIdDirectly(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	mustOK(t, e, "alerts", "list", "--device", "pump-02", "--open", "--category", "monitoring", "-o", "json")
	last := f.requests()[len(f.requests())-1]
	for _, want := range []string{"device_id=" + d2, "resolved=false", "category=monitoring"} {
		if !strings.Contains(last.Query, want) {
			t.Fatalf("the filters go to the server: %s", last.Query)
		}
	}
	if strings.Contains(last.Path, d2) {
		t.Fatal("a device is a query filter and not a path segment")
	}
	mustOK(t, e, "alerts", "show", a2)
	if f.count("GET", "/api/v1/alerts/"+a2) != 1 {
		t.Fatal("alerts show reads one alert by id")
	}
	// --machine still works as the old name
	if out := mustOK(t, e, "alerts", "list", "--machine", "pump-02", "-o", "json"); !strings.Contains(out, a4) {
		t.Fatal(out)
	}
}

func TestAPIErrorCodeIsCarriedIntoJSONErrors(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.queue("GET", "/api/v1/health/summary", step{status: 403, body: `{"code":"session_required","detail":"A signed-in session is needed for this. An API token cannot do it"}`, forever: true})
	_, errs, code := e.run("health", "-o", "json")
	var body map[string]any
	if err := json.Unmarshal([]byte(errs), &body); err != nil || code != ExitForbidden || body["code"] != "forbidden" || body["api_code"] != "session_required" {
		t.Fatalf("%d %s", code, errs)
	}
}
