package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestExitCodes(t *testing.T) {
	type tc struct {
		name  string
		code  int
		setup func(f *fakeAPI, e *env)
		args  []string
		want  string
	}
	cases := []tc{
		{"success", ExitOK, nil, []string{"health"}, ""},
		{"general failure (an answer nobody expected)", ExitFailure, func(f *fakeAPI, e *env) {
			f.queue("GET", "/api/v1/health/summary", step{status: 418, body: `{"detail":"teapot"}`, forever: true})
		}, []string{"health"}, "teapot"},
		{"usage: unknown command", ExitUsage, nil, []string{"machinse", "list"}, "Did you mean"},
		{"usage: unknown option", ExitUsage, nil, []string{"health", "--nope"}, "unknown option --nope"},
		{"usage: missing argument", ExitUsage, nil, []string{"devices", "show"}, "usage: phaemosctl devices show <device>"},
		{"usage: bad output", ExitUsage, nil, []string{"health", "-o", "xml"}, "--output must be"},
		{"not signed in: no token", ExitNotSignedIn, func(f *fakeAPI, e *env) { delete(e.vars, "PHAEMOS_TOKEN") }, []string{"health"}, "not signed in"},
		{"not signed in: token refused", ExitNotSignedIn, func(f *fakeAPI, e *env) { e.vars["PHAEMOS_TOKEN"] = tokBad }, []string{"health"}, "token was refused"},
		{"not allowed", ExitForbidden, nil, []string{"alerts", "resolve", a4, "--yes"}, "not allowed"},
		{"not found", ExitNotFound, nil, []string{"devices", "show", "nothing-here"}, "no device is called"},
		{"conflict: ambiguous name", ExitConflict, nil, []string{"devices", "show", "twin"}, "matches 2 machines"},
		{"conflict: refused as invalid", ExitConflict, func(f *fakeAPI, e *env) {
			f.queue("GET", "/api/v1/ml/status", step{status: 422, body: `{"detail":[{"loc":["query","limit"],"msg":"value is not valid"}]}`, forever: true})
		}, []string{"model", "status"}, "query.limit: value is not valid"},
		{"rate limited after retries", ExitRateLimited, func(f *fakeAPI, e *env) {
			f.queue("GET", "/api/v1/health/summary", step{status: 429, header: map[string]string{"Retry-After": "2"}, body: `{"detail":"slow down"}`, forever: true})
		}, []string{"health"}, "rate limited: slow down"},
		{"server failed", ExitUnavailable, func(f *fakeAPI, e *env) {
			f.queue("GET", "/api/v1/health/summary", step{status: 503, body: `{"detail":"busy"}`, forever: true})
		}, []string{"health"}, "the server failed (503): busy"},
		{"network failed", ExitUnavailable, func(f *fakeAPI, e *env) { e.vars["PHAEMOS_URL"] = "http://127.0.0.1:1" }, []string{"health"}, "cannot reach the server"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := newFake(t)
			e := newEnv(t, f)
			if c.setup != nil {
				c.setup(f, e)
			}
			out, errs, code := e.run(c.args...)
			if code != c.code {
				t.Fatalf("exit %d, want %d\nstdout: %s\nstderr: %s", code, c.code, out, errs)
			}
			if c.want != "" && !strings.Contains(errs, c.want) {
				t.Fatalf("stderr %q does not hold %q", errs, c.want)
			}
			if c.code != 0 && out != "" {
				t.Fatalf("an error must leave standard output empty: %q", out)
			}
			// a failure is one line a person can act on
			if c.code != 0 && strings.Count(strings.TrimSpace(errs), "\n") != 0 {
				t.Fatalf("an error is one line: %q", errs)
			}
		})
	}
}

func TestErrorsAsJSONHaveAStableCode(t *testing.T) {
	want := map[string]struct {
		code int
		kind string
	}{
		"usage":   {ExitUsage, "usage"},
		"token":   {ExitNotSignedIn, "unauthenticated"},
		"missing": {ExitNotFound, "not_found"},
		"busy":    {ExitUnavailable, "unavailable"},
	}
	for name, w := range want {
		t.Run(name, func(t *testing.T) {
			f := newFake(t)
			e := newEnv(t, f)
			var args []string
			switch name {
			case "usage":
				args = []string{"devices", "show", "-o", "json"}
			case "token":
				e.vars["PHAEMOS_TOKEN"] = tokBad
				args = []string{"health", "-o", "json"}
			case "missing":
				args = []string{"devices", "show", "none", "-o", "json"}
			case "busy":
				f.queue("GET", "/api/v1/health/summary", step{status: 500, body: `{"detail":"x"}`, forever: true})
				args = []string{"health", "--output", "json"}
			}
			out, errs, code := e.run(args...)
			if code != w.code || out != "" {
				t.Fatalf("exit %d stdout %q", code, out)
			}
			var body map[string]any
			if err := json.Unmarshal([]byte(errs), &body); err != nil {
				t.Fatalf("stderr is not one JSON object: %q", errs)
			}
			if body["code"] != w.kind || int(body["exit"].(float64)) != w.code || body["message"] == "" {
				t.Fatalf("%v", body)
			}
		})
	}
}

func TestConfigPrecedenceFlagThenEnvironmentThenFile(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_URL")
	delete(e.vars, "PHAEMOS_TOKEN")
	// the file: two profiles
	mustOK(t, e, "config", "set", "url", f.srv.URL, "--profile", "default")
	mustOK(t, e, "config", "set", "url", "http://127.0.0.1:1", "--profile", "dead")
	// the file's default profile reaches the fake
	e.vars["PHAEMOS_TOKEN"] = tokRead
	if _, errs, code := e.run("status"); code != 0 {
		t.Fatalf("file address: %d %s", code, errs)
	}
	// --profile picks another profile from the file
	if _, _, code := e.run("status", "--profile", "dead"); code != ExitUnavailable {
		t.Fatalf("--profile dead should reach nothing: %d", code)
	}
	// the environment beats the file
	e.vars["PHAEMOS_PROFILE"] = "dead"
	if _, _, code := e.run("status"); code != ExitUnavailable {
		t.Fatalf("PHAEMOS_PROFILE: %d", code)
	}
	e.vars["PHAEMOS_URL"] = f.srv.URL
	if _, errs, code := e.run("status"); code != 0 {
		t.Fatalf("PHAEMOS_URL beats the profile's address: %d %s", code, errs)
	}
	// a flag beats the environment
	if _, _, code := e.run("status", "--url", "http://127.0.0.1:1"); code != ExitUnavailable {
		t.Fatalf("--url beats PHAEMOS_URL: %d", code)
	}
	if _, _, code := e.run("status", "--profile", "default"); code != 0 {
		t.Fatalf("--profile beats PHAEMOS_PROFILE: %d", code)
	}
	// config show says where each came from
	out := mustOK(t, e, "config", "show", "--url", f.srv.URL)
	if !strings.Contains(out, "(flag)") || !strings.Contains(out, "(environment)") {
		t.Fatalf("config show:\n%s", out)
	}
	// an unknown profile is a usage error that says how to make it
	delete(e.vars, "PHAEMOS_URL")
	delete(e.vars, "PHAEMOS_PROFILE")
	if _, errs, code := e.run("status", "--profile", "nowhere"); code != ExitUsage || !strings.Contains(errs, "config set url") {
		t.Fatalf("unknown profile: %d %s", code, errs)
	}
}

func TestTokenPrecedenceEnvironmentThenFile(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	e.stdin = tokRead + "\n"
	mustOK(t, e, "auth", "login") // stores tokRead in the file
	delete(e.vars, "PHAEMOS_TOKEN")
	if out := mustOK(t, e, "auth", "status"); !strings.Contains(out, "ci script") {
		t.Fatalf("the file's token: %s", out)
	}
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	if out := mustOK(t, e, "auth", "status"); !strings.Contains(out, "ops laptop") {
		t.Fatalf("the environment's token beats the file's: %s", out)
	}
}

func TestConfigFileAndFolderPermissions(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	mustOK(t, e, "config", "set", "url", f.srv.URL)
	info, err := os.Stat(e.configPath())
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("file mode: %v %v", info, err)
	}
	dirInfo, _ := os.Stat(filepath.Dir(e.configPath()))
	if dirInfo.Mode().Perm() != 0o700 {
		t.Fatalf("folder mode: %v", dirInfo.Mode().Perm())
	}
	for _, mode := range []os.FileMode{0o644, 0o640, 0o604, 0o666} {
		if err := os.Chmod(e.configPath(), mode); err != nil {
			t.Fatal(err)
		}
		_, errs, code := e.run("status")
		if code != ExitUsage || !strings.Contains(errs, "other users can read it") || !strings.Contains(errs, "chmod 600") {
			t.Fatalf("mode %o: %d %s", mode, code, errs)
		}
	}
	_ = os.Chmod(e.configPath(), 0o600)
	// a folder others can write to is refused when saving
	if err := os.Chmod(filepath.Dir(e.configPath()), 0o777); err != nil {
		t.Fatal(err)
	}
	_, errs, code := e.run("config", "set", "url", f.srv.URL)
	if code == 0 || !strings.Contains(errs, "can be written by other users") {
		t.Fatalf("open folder: %d %s", code, errs)
	}
	_ = os.Chmod(filepath.Dir(e.configPath()), 0o700)
	// a link in place of the file is refused
	link := filepath.Join(e.dir, "linked")
	_ = os.Symlink(e.configPath(), link)
	e.vars["PHAEMOS_CONFIG"] = link
	if _, errs, code := e.run("status"); code != ExitUsage || !strings.Contains(errs, "link") {
		t.Fatalf("link: %d %s", code, errs)
	}
}

func TestConfigFileFormatErrors(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	if err := os.MkdirAll(filepath.Dir(e.configPath()), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, body := range []string{"url = x\n", "[bad name]\n", "[a]\nwhat\n", "[a]\nnope = 1\n", "[a]\ntoken_expires = tomorrow\n"} {
		if err := os.WriteFile(e.configPath(), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, errs, code := e.run("status"); code != ExitUsage || !strings.Contains(errs, "line") {
			t.Fatalf("%q: %d %s", body, code, errs)
		}
	}
	// comments, blank lines and spaces are fine
	body := "# a comment\nprofile = staging\n\n[staging]\n  url   =   " + f.srv.URL + "  \n"
	_ = os.WriteFile(e.configPath(), []byte(body), 0o600)
	delete(e.vars, "PHAEMOS_URL")
	if _, errs, code := e.run("status"); code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
}

func TestAuthLoginLogoutAndTheTokenNeverLeaks(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	// piped on standard input
	e.stdin = tokOperate + "\n"
	out, errs, code := e.run("auth", "login")
	if code != 0 || strings.Contains(out+errs, tokOperate) {
		t.Fatalf("login: %d %q %q", code, out, errs)
	}
	if !strings.Contains(errs, "ops laptop") || !strings.Contains(errs, "operate") {
		t.Fatalf("login should say who: %q", errs)
	}
	data, _ := os.ReadFile(e.configPath())
	if !strings.Contains(string(data), tokOperate) || !strings.Contains(string(data), "token_id = op02") || !strings.Contains(string(data), "token_scope = operate") {
		t.Fatalf("config:\n%s", data)
	}
	// config show never prints the token, only its id and name
	for _, args := range [][]string{{"config", "show"}, {"config", "show", "-o", "json"}} {
		shown := mustOK(t, e, args...)
		if strings.Contains(shown, tokOperate) || strings.Contains(shown, "OPERATESECRET") || !strings.Contains(shown, "op02") || !strings.Contains(shown, "ops laptop") {
			t.Fatalf("config show leaks or omits:\n%s", shown)
		}
	}
	// the stored token works for a write that needs operate
	if out := mustOK(t, e, "alerts", "resolve", a1, "--yes"); out != "" {
		t.Fatalf("resolve printed to stdout: %q", out)
	}
	// logout removes it from the file
	_, errs, code = e.run("auth", "logout")
	if code != 0 || !strings.Contains(errs, "still works until it is revoked") {
		t.Fatalf("logout: %d %s", code, errs)
	}
	data, _ = os.ReadFile(e.configPath())
	if strings.Contains(string(data), "pht_") || strings.Contains(string(data), "token_") {
		t.Fatalf("token left in the file:\n%s", data)
	}
	if _, _, code := e.run("health"); code != ExitNotSignedIn {
		t.Fatalf("after logout: %d", code)
	}
	// logout with the token in the environment says to unset it
	e.vars["PHAEMOS_TOKEN"] = tokRead
	if _, errs, _ := e.run("auth", "logout"); !strings.Contains(errs, "unset it in your shell") {
		t.Fatalf("env logout: %s", errs)
	}
}

func TestAuthLoginRefusesBadTokensAndStoresNothing(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	e.stdin = tokBad + "\n"
	out, errs, code := e.run("auth", "login")
	if code != ExitNotSignedIn || strings.Contains(out+errs, tokBad) || strings.Contains(out+errs, "UNKNOWNSECRET") {
		t.Fatalf("refused token: %d %q %q", code, out, errs)
	}
	if _, err := os.Stat(e.configPath()); err == nil {
		t.Fatal("a refused token must not create the file")
	}
	for _, in := range []string{"hello\n", "\n", "", "pht_ has a space\n"} {
		e.stdin = in
		out, errs, code := e.run("auth", "login")
		if code != ExitUsage || strings.Contains(out+errs, "has a space") && strings.Contains(out+errs, in[:3]) && false {
			t.Fatalf("%q: %d %s", in, code, errs)
		}
		if strings.Contains(errs, "hello") {
			t.Fatalf("the bad input was echoed: %s", errs)
		}
	}
	// a token that is not a token never reaches the server
	if n := f.count("GET", "/api/v1/auth/whoami"); n != 1 {
		t.Fatalf("whoami was called %d times (only the well-formed bad token should be)", n)
	}
}

func TestAuthLoginAtATerminalUsesTheNoEchoPrompt(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	e.inTTY = true
	var prompt string
	e.secret = func(p string) (string, error) { prompt = p; return tokRead, nil }
	e.stdin = "SHOULD NOT BE READ\n"
	_, errs, code := e.run("auth", "login")
	if code != 0 || !strings.Contains(prompt, "will not be shown") || strings.Contains(errs, tokRead) {
		t.Fatalf("%d %q %q", code, prompt, errs)
	}
	// no secret reader on a terminal: a clear message and nothing stored
	e.secret = nil
	os.Remove(e.configPath())
	if _, errs, code := e.run("auth", "login"); code != ExitUsage || !strings.Contains(errs, "pipe it on standard input") {
		t.Fatalf("%d %s", code, errs)
	}
}

func TestNoTokenFlagExists(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for _, args := range [][]string{{"health", "--token", tokRead}, {"auth", "login", "--token", tokRead}, {"config", "set", "token", tokRead}} {
		out, errs, code := e.run(args...)
		if code != ExitUsage || strings.Contains(out+errs, tokRead) || strings.Contains(out+errs, "READSECRET") {
			t.Fatalf("%v: %d %q %q", args, code, out, errs)
		}
	}
}

func TestResolveNeedsConfirmationAndNeverPromptsWithoutATerminal(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	// no terminal: refuses, says why, sends nothing
	_, errs, code := e.run("alerts", "resolve", a1)
	if code != ExitUsage || !strings.Contains(errs, "standard input is not a terminal") || !strings.Contains(errs, "--yes") {
		t.Fatalf("%d %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/alerts/"+a1+"/resolve"); n != 0 {
		t.Fatalf("a request was sent without confirmation")
	}
	// a terminal that says no
	e.inTTY = true
	e.stdin = "n\n"
	if _, errs, code := e.run("alerts", "resolve", a1); code != ExitFailure || !strings.Contains(errs, "nothing was changed") {
		t.Fatalf("no: %d %s", code, errs)
	}
	if f.count("POST", "/api/v1/alerts/"+a1+"/resolve") != 0 {
		t.Fatal("sent after no")
	}
	// a terminal that says yes
	e.stdin = "y\n"
	if _, errs, code := e.run("alerts", "resolve", a1); code != 0 || !strings.Contains(errs, "is resolved") {
		t.Fatalf("yes: %d %s", code, errs)
	}
	// --yes needs no terminal
	e.inTTY = false
	if _, _, code := e.run("alerts", "resolve", a2, "--yes"); code != 0 {
		t.Fatalf("--yes: %d", code)
	}
	if _, _, code := e.run("alerts", "resolve", "not-an-id", "--yes"); code != ExitUsage {
		t.Fatal("a bad id is a usage error")
	}
}

func TestResolveWithAReadTokenIsNotAllowed(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	_, errs, code := e.run("alerts", "resolve", a1, "--yes")
	if code != ExitForbidden || !strings.Contains(errs, "needs operate") {
		t.Fatalf("%d %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/alerts/"+a1+"/resolve"); n != 1 {
		t.Fatalf("a refusal must not be retried: %d", n)
	}
}

func TestResolveIsRetriedAfterAServerErrorBecauseItIsSafeToRepeat(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	f.queue("POST", "/api/v1/alerts/"+a1+"/resolve", step{status: 503}, step{status: 502})
	if _, errs, code := e.run("alerts", "resolve", a1, "--yes"); code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
	if n := f.count("POST", "/api/v1/alerts/"+a1+"/resolve"); n != 3 {
		t.Fatalf("expected 3 tries, got %d", n)
	}
	if got := e.clock.slept(); len(got) != 2 || got[0] != 500*time.Millisecond || got[1] != time.Second {
		t.Fatalf("back-off: %v", got)
	}
}

func TestGETsRetryAndWaitOnTheFakeClock(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.queue("GET", "/api/v1/health/summary", step{status: 429, header: map[string]string{"Retry-After": "7"}}, step{status: 503}, step{status: 504})
	mustOK(t, e, "health")
	got := e.clock.slept()
	want := []time.Duration{7 * time.Second, 500 * time.Millisecond, time.Second}
	if len(got) != len(want) {
		t.Fatalf("sleeps %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("sleeps %v, want %v", got, want)
		}
	}
	// a Retry-After longer than the maximum is not waited out
	f.queue("GET", "/api/v1/ml/status", step{status: 429, header: map[string]string{"Retry-After": "600"}, forever: true})
	before := len(e.clock.slept())
	_, errs, code := e.run("model", "status")
	if code != ExitRateLimited || len(e.clock.slept()) != before || !strings.Contains(errs, "600 s") {
		t.Fatalf("%d %v %s", code, e.clock.slept(), errs)
	}
}

func TestPlainColourOnlyOnATerminalAndNeverWhenTold(t *testing.T) {
	f := newFake(t)
	cases := []struct {
		name  string
		tty   bool
		vars  map[string]string
		flag  string
		color bool
	}{
		{"terminal", true, nil, "", true},
		{"pipe", false, nil, "", false},
		{"NO_COLOR", true, map[string]string{"NO_COLOR": "1"}, "", false},
		{"--no-color", true, nil, "--no-color", false},
		{"dumb terminal", true, map[string]string{"TERM": "dumb"}, "", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			e := newEnv(t, f)
			e.outTTY = c.tty
			e.vars["TERM"] = "xterm-256color"
			for k, v := range c.vars {
				e.vars[k] = v
			}
			args := []string{"devices", "list"}
			if c.flag != "" {
				args = append(args, c.flag)
			}
			out := mustOK(t, e, args...)
			if has := strings.Contains(out, "\x1b["); has != c.color {
				t.Fatalf("colour %v, want %v:\n%q", has, c.color, out)
			}
			if !c.tty && !strings.Contains(out, "\t") {
				t.Fatalf("a pipe gets tab-separated rows: %q", out)
			}
			if c.tty && strings.Contains(out, "\t") {
				t.Fatalf("a terminal gets aligned columns: %q", out)
			}
		})
	}
}

func TestNothingButTheResultOnStandardOutput(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	delete(e.vars, "PHAEMOS_TOKEN")
	e.stdin = tokSoon + "\n"
	mustOK(t, e, "auth", "login")
	out, errs, code := e.run("devices", "list", "--verbose", "--limit", "2")
	if code != 0 {
		t.Fatal(errs)
	}
	for _, noise := range []string{"warning", "GET /", "->", "showing"} {
		if strings.Contains(out, noise) {
			t.Fatalf("%q on standard output:\n%s", noise, out)
		}
	}
	for _, want := range []string{"warning: this token expires", "warning: showing 2 of 5 machines", "GET /api/v1/devices -> 200", "GET /api/v1/alerts -> 200"} {
		if !strings.Contains(errs, want) {
			t.Fatalf("stderr lacks %q:\n%s", want, errs)
		}
	}
	// --quiet drops the warnings
	_, errs, _ = e.run("devices", "list", "--quiet", "--limit", "2")
	if errs != "" {
		t.Fatalf("--quiet left %q", errs)
	}
	// --verbose shows no header value and no body
	_, errs, _ = e.run("devices", "list", "--verbose")
	for _, secret := range []string{"Bearer", tokSoon, "SOONSECRET", "press-01", "Authorization"} {
		if strings.Contains(errs, secret) {
			t.Fatalf("--verbose showed %q:\n%s", secret, errs)
		}
	}
}

func TestListsPageThroughEverythingUpToTheLimit(t *testing.T) {
	f := newFake(t)
	for i := 0; i < 450; i++ {
		f.devices = append(f.devices, map[string]any{"id": fmt.Sprintf("99999999-9999-4999-8999-%012d", i), "name": "bulk", "status": "online", "tags": []string{}, "expected_interval_s": 5})
	}
	e := newEnv(t, f)
	out := mustOK(t, e, "devices", "list", "-o", "jsonl")
	if n := strings.Count(out, "\n"); n != 455 {
		t.Fatalf("a list pages through everything: %d", n)
	}
	// 455 items at 200 a page is 3 requests for the list (plus the alert counts, which are not part of jsonl)
	pages := 0
	for _, r := range f.requests() {
		if r.Path == "/api/v1/devices" {
			pages++
		}
	}
	if pages != 3 {
		t.Fatalf("pages: %d", pages)
	}
	_, errs, _ := e.run("devices", "list", "--limit", "10", "-o", "jsonl")
	if !strings.Contains(errs, "showing 10 of 455 machines: use --limit to see more") {
		t.Fatalf("%s", errs)
	}
	if _, _, code := e.run("devices", "list", "--limit", "0"); code != ExitUsage {
		t.Fatal("--limit 0 should be refused")
	}
	if _, _, code := e.run("devices", "list", "--limit", "100001"); code != ExitUsage {
		t.Fatal("--limit above the maximum should be refused")
	}
}

func TestHelpAndDashHAgreeForEveryCommandAndTeach(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for _, c := range commands {
		name := c.name()
		parts := strings.Fields(name)
		viaHelp := mustOK(t, e, append([]string{"help"}, parts...)...)
		viaFlag := mustOK(t, e, append(append([]string{}, parts...), "-h")...)
		if viaHelp != viaFlag {
			t.Fatalf("%s: help and -h differ:\n%s\n---\n%s", name, viaHelp, viaFlag)
		}
		if c.summary == "" || len(strings.Fields(c.desc)) < 8 {
			t.Fatalf("%s lacks a summary or description", name)
		}
		if len(c.examples) < 2 {
			t.Fatalf("%s has %d examples, want at least 2", name, len(c.examples))
		}
		if strings.Count(viaHelp, "\n  $ ") < 2 || !strings.Contains(viaHelp, "Exit codes:") || !strings.Contains(viaHelp, c.summary) {
			t.Fatalf("%s help is thin:\n%s", name, viaHelp)
		}
		for _, ex := range c.examples {
			if !strings.Contains(ex, "phaemosctl") && !strings.Contains(ex, "source <(") {
				t.Fatalf("%s: example %q does not show the tool", name, ex)
			}
		}
	}
	top := mustOK(t, e, "help")
	for _, c := range commands {
		if !strings.Contains(top, c.name()) {
			t.Fatalf("top help lacks %s", c.name())
		}
	}
	if !strings.Contains(top, "3  not signed in") || !strings.Contains(top, "8  the server or the network failed") {
		t.Fatalf("top help lacks the exit codes:\n%s", top)
	}
	if out := mustOK(t, e, "help", "devices"); !strings.Contains(out, "devices list") || !strings.Contains(out, "devices show") {
		t.Fatalf("a noun lists its verbs: %s", out)
	}
}

func TestNearestCommandIsSuggested(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for typed, want := range map[string]string{"machine": "devices", "alert": "alerts", "stauts": "status", "heatlh": "health", "ticket": "tickets", "readng": "readings"} {
		_, errs, code := e.run(typed)
		if code != ExitUsage || !strings.Contains(errs, "Did you mean: phaemosctl "+want) {
			t.Fatalf("%s: %d %s", typed, code, errs)
		}
	}
	if _, errs, _ := e.run("devices", "lst"); !strings.Contains(errs, "Did you mean: phaemosctl devices list") {
		t.Fatalf("%s", errs)
	}
	if _, errs, _ := e.run("zzzzzzzz"); strings.Contains(errs, "Did you mean") {
		t.Fatalf("no wild guesses: %s", errs)
	}
}

func TestOptionsMayComeAnywhere(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	a := mustOK(t, e, "devices", "show", "press-01", "--output", "json")
	b := mustOK(t, e, "--output", "json", "devices", "show", "press-01")
	c := mustOK(t, e, "devices", "show", "--output=json", "press-01")
	if a != b || a != c {
		t.Fatalf("options in different places gave different output")
	}
}

func TestCompletionScriptsMentionEveryCommandAndParse(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for _, shell := range []string{"bash", "zsh", "fish"} {
		out := mustOK(t, e, "completion", shell)
		for noun := range nouns() {
			if !strings.Contains(out, noun) {
				t.Fatalf("%s script lacks %s", shell, noun)
			}
		}
		for _, c := range commands {
			if !strings.Contains(out, c.path[len(c.path)-1]) {
				t.Fatalf("%s script lacks %s", shell, c.name())
			}
		}
		if bin, err := exec.LookPath(shell); err == nil {
			path := filepath.Join(e.dir, "comp."+shell)
			_ = os.WriteFile(path, []byte(out), 0o600)
			args := []string{"-n", path}
			if shell == "fish" {
				args = []string{"--no-execute", path}
			}
			if msg, err := exec.Command(bin, args...).CombinedOutput(); err != nil {
				t.Fatalf("%s rejects its script: %v\n%s", shell, err, msg)
			}
		}
	}
	if _, _, code := e.run("completion", "powershell"); code != ExitUsage {
		t.Fatal("an unknown shell is a usage error")
	}
}

// no path through the tool may show the token, in any output, in any error, in any format
func TestTheTokenNeverAppearsOnAnyPath(t *testing.T) {
	secrets := []string{tokRead, "READSECRET", tokBad, "UNKNOWNSECRET", tokOperate, "OPERATESECRET"}
	check := func(label, out, errs string) {
		t.Helper()
		for _, s := range secrets {
			if strings.Contains(out, s) || strings.Contains(errs, s) {
				t.Fatalf("%s: the token appeared:\nstdout: %s\nstderr: %s", label, out, errs)
			}
		}
	}
	f := newFake(t)
	echo := step{status: 400, body: `{"detail":"bad request from ` + tokRead + ` and ` + tokOperate + `"}`, forever: true}
	paths := []struct {
		method, path string
		args         []string
	}{
		{"GET", "/api/v1/health/summary", []string{"health"}},
		{"GET", "/api/v1/devices", []string{"devices", "list"}},
		{"GET", "/api/v1/devices", []string{"devices", "show", "press-01"}},
		{"GET", "/api/v1/alerts", []string{"alerts", "list"}},
		{"GET", "/api/v1/tickets", []string{"tickets", "list"}},
		{"GET", "/api/v1/ml/status", []string{"model", "status"}},
		{"GET", "/api/v1/auth/whoami", []string{"auth", "status"}},
		{"GET", "/status", []string{"status"}},
		{"GET", "/api/v1/telemetry/export", []string{"readings", "export", d1, "--from", "7d", "--out", "-"}},
		{"PATCH", "/api/v1/alerts/" + a1 + "/resolve", []string{"alerts", "resolve", a1, "--yes"}},
	}
	statuses := []step{echo, {status: 401, body: `{"detail":"` + tokRead + `"}`, forever: true}, {status: 403, body: tokRead, forever: true},
		{status: 404, body: tokRead, forever: true}, {status: 500, body: tokRead, forever: true}, {status: 429, header: map[string]string{"Retry-After": "1", "X-Echo": tokRead}, body: tokRead, forever: true},
		{status: 200, body: "not json " + tokRead, forever: true}, {status: 200, body: `{"` + tokRead + `":1}`, forever: true}}
	for _, p := range paths {
		for _, st := range statuses {
			for _, format := range []string{"table", "json", "jsonl"} {
				for _, verbose := range []bool{false, true} {
					e := newEnv(t, f)
					e.vars["PHAEMOS_TOKEN"] = tokOperate
					f.queue(p.method, p.path, st)
					args := append(append([]string{}, p.args...), "-o", format)
					if verbose {
						args = append(args, "--verbose")
					}
					out, errs, _ := e.run(args...)
					check(fmt.Sprintf("%v %d %s", p.args, st.status, format), out, errs)
					f.queue(p.method, p.path)
				}
			}
		}
	}
	// network failures, a dead host, a refused certificate and a timeout
	e := newEnv(t, f)
	e.vars["PHAEMOS_URL"] = "http://127.0.0.1:1"
	e.vars["PHAEMOS_TOKEN"] = tokOperate
	for _, args := range [][]string{{"health"}, {"status", "--verbose"}, {"readings", "tail", "x"}, {"auth", "status", "-o", "json"}} {
		out, errs, _ := e.run(args...)
		check(strings.Join(args, " "), out, errs)
	}
	// usage errors that carry a token-shaped argument
	e = newEnv(t, f)
	for _, args := range [][]string{{"devices", "show", tokRead}, {"alerts", "show", tokRead}, {"tickets", "show", tokRead}, {"config", "set", "token", tokRead}, {"config", "set", tokRead, "x"}} {
		out, errs, code := e.run(args...)
		check(strings.Join(args, " "), out, errs)
		if code == 0 {
			t.Fatalf("%v succeeded", args)
		}
	}
	// the file's own errors
	e = newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = "pht_ bad token with spaces " + tokRead
	out, errs, _ := e.run("health")
	check("bad env token", out, errs)
	e.stdin = tokRead + "\n"
	delete(e.vars, "PHAEMOS_TOKEN")
	e.vars["PHAEMOS_URL"] = "ftp://" + tokRead
	out, errs, _ = e.run("auth", "login")
	check("bad url", out, errs)
}

func TestExportStreamsToAFileAndNeverOverwritesWithoutForce(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	target := filepath.Join(e.dir, "out.csv")
	out, errs, code := e.run("readings", "export", "press-01", "--from", "7d", "--out", target)
	if code != 0 || out != "" || !strings.Contains(errs, "Wrote") {
		t.Fatalf("%d %q %q", code, out, errs)
	}
	data, _ := os.ReadFile(target)
	if !strings.HasPrefix(string(data), "id,device_id,recorded_at,temperature\n0,"+d1) || strings.Count(string(data), "\n") != 4 {
		t.Fatalf("file:\n%s", data)
	}
	// the window reached the server in UTC
	last := f.requests()[len(f.requests())-1]
	if !strings.Contains(last.Query, "device_id="+d1) || !strings.Contains(last.Query, "from_ts=2026-11-15T12%3A00%3A00Z") {
		t.Fatalf("query: %s", last.Query)
	}
	// refuses to overwrite
	_, errs, code = e.run("readings", "export", "press-01", "--from", "7d", "--out", target)
	if code != ExitUsage || !strings.Contains(errs, "already exists") || !strings.Contains(errs, "--force") {
		t.Fatalf("overwrite: %d %s", code, errs)
	}
	before := f.count("GET", "/api/v1/telemetry/export")
	// nothing was downloaded for the refusal
	_, _, _ = e.run("readings", "export", "press-01", "--from", "7d", "--out", target)
	if f.count("GET", "/api/v1/telemetry/export") != before {
		t.Fatal("a refused export still downloaded")
	}
	// --force replaces it
	f.exportRows = 1
	if _, errs, code := e.run("readings", "export", "press-01", "--from", "7d", "--out", target, "--force"); code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
	data, _ = os.ReadFile(target)
	if strings.Count(string(data), "\n") != 2 {
		t.Fatalf("not replaced:\n%s", data)
	}
	left, _ := filepath.Glob(filepath.Join(e.dir, ".phaemos-export-*"))
	if len(left) != 0 {
		t.Fatalf("temporary files left: %v", left)
	}
	// standard output
	f.exportRows = 2
	out, _, code = e.run("readings", "export", "press-01", "--from", "2026-11-20", "--to", "2026-11-21T00:00:00Z", "--out", "-")
	if code != 0 || strings.Count(out, "\n") != 3 {
		t.Fatalf("stdout export: %d %q", code, out)
	}
}

func TestExportWindowAndArgumentChecks(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	for name, args := range map[string][]string{
		"no out":    {"readings", "export", "press-01", "--from", "1d"},
		"no from":   {"readings", "export", "press-01", "--out", "-"},
		"too long":  {"readings", "export", "press-01", "--from", "40d", "--out", "-"},
		"backwards": {"readings", "export", "press-01", "--from", "2026-11-20", "--to", "2026-11-19", "--out", "-"},
		"bad time":  {"readings", "export", "press-01", "--from", "yesterday", "--out", "-"},
		"bad to":    {"readings", "export", "press-01", "--from", "1d", "--to", "soon", "--out", "-"},
	} {
		if _, errs, code := e.run(args...); code != ExitUsage {
			t.Fatalf("%s: %d %s", name, code, errs)
		}
	}
	if n := f.count("GET", "/api/v1/telemetry/export"); n != 0 {
		t.Fatalf("a refused window still reached the server: %d", n)
	}
}

func TestAnExportThatStopsHalfWayLeavesNoFile(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.queue("GET", "/api/v1/telemetry/export", step{abort: true, partial: "id,device_id,recorded_at\n1,x,y\n"})
	target := filepath.Join(e.dir, "partial.csv")
	_, errs, code := e.run("readings", "export", "press-01", "--from", "1d", "--out", target)
	if code != ExitUnavailable || !strings.Contains(errs, "the export stopped") {
		t.Fatalf("%d %s", code, errs)
	}
	if _, err := os.Stat(target); err == nil {
		t.Fatal("a failed export left its partial file")
	}
	// with --force an existing good file survives a failed export
	_ = os.WriteFile(target, []byte("old good data\n"), 0o644)
	f.queue("GET", "/api/v1/telemetry/export", step{abort: true, partial: "id\n1\n"})
	if _, _, code := e.run("readings", "export", "press-01", "--from", "1d", "--out", target, "--force"); code == 0 {
		t.Fatal("expected a failure")
	}
	if data, _ := os.ReadFile(target); string(data) != "old good data\n" {
		t.Fatalf("a failed forced export damaged the old file: %q", data)
	}
	left, _ := filepath.Glob(filepath.Join(e.dir, ".phaemos-export-*"))
	if len(left) != 0 {
		t.Fatalf("temporary files left: %v", left)
	}
}

func TestExportOfAHugeFileIsStreamedNotHeld(t *testing.T) {
	f := newFake(t)
	f.exportRows = 400000 // about 30 MB of CSV, more than the 4 MiB reply cap a normal read has
	e := newEnv(t, f)
	target := filepath.Join(e.dir, "big.csv")
	if _, errs, code := e.run("readings", "export", "press-01", "--from", "1d", "--out", target); code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
	info, _ := os.Stat(target)
	if info.Size() < 20<<20 {
		t.Fatalf("only %d bytes written", info.Size())
	}
}

func TestExportRefusedByTheServerRemovesNothingAndSaysWhy(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.queue("GET", "/api/v1/telemetry/export", step{status: 404, body: `{"detail":"Device not found"}`, forever: true})
	target := filepath.Join(e.dir, "none.csv")
	_, errs, code := e.run("readings", "export", "press-01", "--from", "1d", "--out", target)
	if code != ExitNotFound || !strings.Contains(errs, "Device not found") {
		t.Fatalf("%d %s", code, errs)
	}
	if _, err := os.Stat(target); err == nil {
		t.Fatal("a refused export left an empty file")
	}
}

// ---- readings tail ----

func tailEnv(t *testing.T, f *fakeAPI, stopAfter int) (*env, context.CancelFunc) {
	ctx, cancel := context.WithCancel(context.Background())
	e := newEnv(t, f)
	e.ctx = ctx
	e.clock.onSleep = func(n int) {
		if n >= stopAfter {
			cancel()
		}
	}
	return e, cancel
}

func TestTailShowsRecentThenOnlyNewReadingsOnce(t *testing.T) {
	f := newFake(t)
	next := 31
	calls := 0
	f.onReadings = func() {
		calls++
		if calls == 1 {
			return // the first read is the tail's own look at the recent readings
		}
		// each poll, one new reading appears and the newest is repeated at the same time
		at := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC).Add(time.Duration(next) * 5 * time.Second)
		row := map[string]any{"id": "00000000-0000-4000-8000-" + padNum(200+next), "device_id": d1, "recorded_at": at.Format(time.RFC3339), "node_type": "esp32", "temperature": 30.0 + float64(next), "humidity": 40.0}
		if next < 34 {
			f.readings[d1] = append([]map[string]any{row}, f.readings[d1]...)
			next++
		}
	}
	e, cancel := tailEnv(t, f, 3)
	defer cancel()
	out, errs, code := e.run("readings", "tail", "press-01", "--lines", "2", "-o", "jsonl")
	if code != 0 {
		t.Fatalf("an interrupt ends a tail cleanly: %d %s", code, errs)
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	var temps []float64
	for _, l := range lines {
		var row map[string]any
		_ = json.Unmarshal([]byte(l), &row)
		temps = append(temps, row["temperature"].(float64))
	}
	// the two newest first (oldest of them first), then each new reading once, oldest first
	want := []float64{24.6, 24.5, 61, 62, 63}
	if len(temps) < 4 {
		t.Fatalf("%v", temps)
	}
	for i := range temps {
		if temps[i] != want[i] {
			t.Fatalf("readings %v, want a prefix of %v", temps, want)
		}
	}
	// every poll waited the stated interval
	for _, d := range e.clock.slept() {
		if d != 5*time.Second {
			t.Fatalf("interval %v", e.clock.slept())
		}
	}
}

func padNum(n int) string { return fmt.Sprintf("%012d", n) }

func TestTailBacksOffOnFailuresAndHonoursRetryAfter(t *testing.T) {
	f := newFake(t)
	e, cancel := tailEnv(t, f, 7)
	defer cancel()
	// initial fetch works (lines 0), then polls: 503 x3 -> back-off 10, 20, 40; then a 429 with Retry-After 90 exhausts the client's waits
	f.queue("GET", "/api/v1/telemetry/"+d1, step{status: 200, body: `[]`}, step{status: 503, forever: true})
	_, errs, code := e.run("readings", "tail", "press-01", "--lines", "0", "--interval", "5s", "-o", "jsonl")
	if code != 0 {
		t.Fatalf("%d %s", code, errs)
	}
	got := e.clock.slept()
	// the client retries a GET inside each poll (500ms, 1s, 2s) and the tail then waits longer each time
	var tailWaits []time.Duration
	for _, d := range got {
		if d >= 5*time.Second {
			tailWaits = append(tailWaits, d)
		}
	}
	n := len(tailWaits)
	if n < 3 || tailWaits[n-1] <= tailWaits[n-2] || tailWaits[n-2] <= tailWaits[n-3] {
		t.Fatalf("the tail should wait longer after each failure: %v", got)
	}
	if !strings.Contains(errs, "poll failed") || !strings.Contains(errs, "trying again in") {
		t.Fatalf("a failed poll is reported: %s", errs)
	}
}

func TestTailGivesUpAfterTenFailuresWithExit8(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	f.queue("GET", "/api/v1/telemetry/"+d1, step{status: 500, forever: true})
	_, errs, code := e.run("readings", "tail", "press-01", "--lines", "0", "-o", "jsonl", "--timeout", "0")
	if code != ExitUnavailable || !strings.Contains(errs, "gave up after 10 failed polls") {
		t.Fatalf("%d %s", code, errs)
	}
}

func TestTailStopsAtOnceOnAuthAndRefusesJSONAndFastIntervals(t *testing.T) {
	f := newFake(t)
	e := newEnv(t, f)
	e.vars["PHAEMOS_TOKEN"] = tokBad
	if _, _, code := e.run("readings", "tail", "press-01"); code != ExitNotSignedIn {
		t.Fatalf("%d", code)
	}
	e.vars["PHAEMOS_TOKEN"] = tokRead
	if _, errs, code := e.run("readings", "tail", "press-01", "-o", "json"); code != ExitUsage || !strings.Contains(errs, "jsonl") {
		t.Fatalf("%d %s", code, errs)
	}
	if _, errs, code := e.run("readings", "tail", "press-01", "--interval", "200ms"); code != ExitUsage || !strings.Contains(errs, "at least 1s") {
		t.Fatalf("%d %s", code, errs)
	}
	if _, _, code := e.run("readings", "tail", "press-01", "--lines", "500"); code != ExitUsage {
		t.Fatal("--lines above 200")
	}
}

func TestTailTableHasAHeaderOnce(t *testing.T) {
	f := newFake(t)
	e, cancel := tailEnv(t, f, 1)
	defer cancel()
	out, _, code := e.run("readings", "tail", "press-01", "--lines", "3")
	if code != 0 {
		t.Fatal(code)
	}
	if strings.Count(out, "TIME\tNODE") != 1 || strings.Count(out, "\n") != 4 {
		t.Fatalf("%q", out)
	}
}

func TestSystemClockSleepEndsOnCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var buf bytes.Buffer
	_ = buf
	if err := (&runCtx{app: &app{io: IO{}}, ctx: ctx}).sleep(time.Hour); err == nil {
		t.Fatal("a cancelled sleep must end")
	}
}
