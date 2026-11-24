package cli

import (
	"os"
	"strings"
	"testing"
	"time"
)

func noDoubleSlash(t *testing.T, f *fakeAPI) {
	t.Helper()
	for _, r := range f.requests() {
		if strings.Contains(r.Path, "//") || (len(r.Path) > 1 && strings.HasSuffix(r.Path, "/")) {
			t.Fatalf("a request had a double or trailing slash: %q", r.Path)
		}
	}
}

func TestTrailingSlashesInTheAddressNeverReachARequest(t *testing.T) {
	f := newFake(t)
	for name, set := range map[string]func(e *env) []string{
		"environment": func(e *env) []string { e.vars["PHAEMOS_URL"] = f.srv.URL + "///"; return nil },
		"flag":        func(e *env) []string { return []string{"--url", f.srv.URL + "/"} },
		"config file": func(e *env) []string {
			delete(e.vars, "PHAEMOS_URL")
			_ = os.MkdirAll(e.dir+"/cfg", 0o700)
			_ = os.WriteFile(e.configPath(), []byte("[default]\nurl = "+f.srv.URL+"//\n"), 0o600)
			return nil
		},
	} {
		t.Run(name, func(t *testing.T) {
			e := newEnv(t, f)
			extra := set(e)
			before := len(f.requests())
			for _, args := range [][]string{{"health"}, {"devices", "list"}, {"alerts", "show", a1}, {"readings", "latest", d1}, {"status"}} {
				if _, errs, code := e.run(append(args, extra...)...); code != 0 {
					t.Fatalf("%v: %d %s", args, code, errs)
				}
			}
			if len(f.requests()) == before {
				t.Fatal("nothing was sent")
			}
			noDoubleSlash(t, f)
		})
	}
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	e.vars["PHAEMOS_URL"] = f.srv.URL + "/"
	mustOK(t, e, "dev", "send", "--json", `{"device_id":"d"}`)
	noDoubleSlash(t, f)
}

func TestConfigSetStoresTheAddressWithoutTheSlash(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	mustOK(t, e, "config", "set", "url", f.srv.URL+"//")
	data, _ := os.ReadFile(e.configPath())
	if !strings.Contains(string(data), "url = "+f.srv.URL+"\n") {
		t.Fatalf("%s", data)
	}
}

func TestAFullIngestAddressIsRefusedWithAPlainMessage(t *testing.T) {
	f := newFake(t)
	for _, bad := range []string{"https://api.example.org/api/v1/telemetry", "https://api.example.org/api/v1/telemetry/", "https://api.example.org/api/"} {
		e := newEnv(t, f)
		e.vars["PHAEMOS_URL"] = bad
		_, errs, code := e.run("health")
		if code != ExitUsage || !strings.Contains(errs, "base address only") || !strings.Contains(errs, "remove the path") {
			t.Fatalf("%s: %d %s", bad, code, errs)
		}
		if _, errs, code := e.run("config", "set", "url", bad); code != ExitUsage || !strings.Contains(errs, "base address only") {
			t.Fatalf("config set %s: %d %s", bad, code, errs)
		}
		e.vars["PHAEMOS_URL"] = f.srv.URL
		if _, errs, code := e.run("health", "--url", bad); code != ExitUsage || !strings.Contains(errs, "base address only") {
			t.Fatalf("--url %s: %d %s", bad, code, errs)
		}
	}
	if n := len(f.requests()); n != 0 {
		t.Fatalf("a refused address sent %d requests", n)
	}
}

func TestA404OnAPostIsAWrongAddressReportedOnceAndNeverRetried(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_DEVICE_KEY"] = devKey
	f.queue("POST", "/api/v1/telemetry", step{status: 404, body: `{"code":"not_found","detail":"Not Found"}`, forever: true})
	_, errs, code := e.run("dev", "send", "--json", `{"device_id":"d"}`)
	if code != ExitNotFound || !strings.Contains(errs, "the address is wrong") || !strings.Contains(errs, "no trailing slash") {
		t.Fatalf("%d %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/telemetry"); n != 1 || len(e.clock.slept()) != 0 {
		t.Fatalf("a 404 post was sent %d times with waits %v", n, e.clock.slept())
	}
	// load stops at the first 404 and says so once
	before := f.count("POST", "/api/v1/telemetry")
	_, errs, code = e.run("dev", "load", "--requests", "20", "--rate", "0")
	if code != ExitNotFound || strings.Count(errs, "the address is wrong") != 1 {
		t.Fatalf("%d %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/telemetry") - before; n > 3 {
		t.Fatalf("load kept posting after a 404: %d posts", n)
	}
}

func TestDoctorCatchesAWrongAddressAndAStrippedSlash(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.statusTime = time.Now()
	e.clock.now = time.Now()
	e.vars["PHAEMOS_URL"] = f.srv.URL + "/"
	out, _, code := e.run("doctor")
	if code != 0 || !strings.Contains(out, "address slash") || !strings.Contains(out, "ends in a slash") {
		t.Fatalf("a stripped slash is a warning: %d\n%s", code, out)
	}
	if !strings.Contains(out, "server version 1.0.0") {
		t.Fatalf("doctor shows the server's version from /status:\n%s", out)
	}
	// a full ingest address is a usage failure with the plain message
	e.vars["PHAEMOS_URL"] = f.srv.URL + "/api/v1/telemetry/"
	out, _, code = e.run("doctor")
	if code != ExitUsage || !strings.Contains(out, "base address only") {
		t.Fatalf("%d\n%s", code, out)
	}
	// a server that answers 404 for /status: the address is probably wrong
	e.vars["PHAEMOS_URL"] = f.srv.URL
	f.queue("GET", "/status", step{status: 404, body: `{"code":"not_found","detail":"Not Found"}`, forever: true})
	out, _, code = e.run("doctor")
	if code != ExitNotFound || !strings.Contains(out, "no path and no trailing slash") {
		t.Fatalf("%d\n%s", code, out)
	}
}

func TestDoctorUsesTheServersClockFromStatusAndFallsBackToTheDateHeader(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.statusTime = time.Now()
	e.clock.now = time.Now().Add(2 * time.Hour)
	out, _, code := e.run("doctor")
	if code != ExitFailure || !strings.Contains(out, "(updated_at)") {
		t.Fatalf("%d\n%s", code, out)
	}
	f.queue("GET", "/status", step{status: 200, body: `{"status":"operational"}`, forever: true})
	out, _, code = e.run("doctor")
	if code != ExitFailure || !strings.Contains(out, "(Date header)") {
		t.Fatalf("%d\n%s", code, out)
	}
}
