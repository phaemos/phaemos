package api

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type fakeClock struct {
	now    time.Time
	sleeps []time.Duration
}

func (c *fakeClock) Now() time.Time { return c.now }
func (c *fakeClock) Sleep(ctx context.Context, d time.Duration) error {
	c.sleeps = append(c.sleeps, d)
	c.now = c.now.Add(d)
	return ctx.Err()
}

func toolClient(url string) (*Client, *fakeClock) {
	c := New(url, "")
	c.Token = "pht_abc123_SECRET-not-real"
	c.Retry = DefaultRetry
	clock := &fakeClock{now: time.Unix(1_800_000_000, 0)}
	c.Clock = clock
	return c, clock
}

// ---- the pager ----

func listServer(t *testing.T, total int, skipName string, maxPage int, withTotal bool) (*httptest.Server, *atomic.Int32) {
	var pages atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		pages.Add(1)
		q := r.URL.Query()
		skip, _ := strconv.Atoi(q.Get(skipName))
		limit, _ := strconv.Atoi(q.Get("limit"))
		if limit > maxPage {
			w.WriteHeader(422)
			_, _ = w.Write([]byte(`{"detail":"limit too large"}`))
			return
		}
		if withTotal {
			w.Header().Set("X-Total-Count", strconv.Itoa(total))
		}
		var items []map[string]any
		for i := skip; i < min(skip+limit, total); i++ {
			items = append(items, map[string]any{"n": i})
		}
		_ = json.NewEncoder(w).Encode(items)
	}))
	t.Cleanup(srv.Close)
	return srv, &pages
}

func TestPagerWalksEveryPageWhicheverParameterTheRouteReads(t *testing.T) {
	for _, name := range []string{"skip", "offset"} {
		t.Run(name, func(t *testing.T) {
			srv, pages := listServer(t, 1234, name, Style.MaxPage, true)
			c, _ := toolClient(srv.URL)
			res, err := c.List(context.Background(), "/x", nil, Style, 5000)
			if err != nil {
				t.Fatal(err)
			}
			if len(res.Items) != 1234 || res.Total != 1234 || res.More {
				t.Fatalf("%d items, total %d, more %v", len(res.Items), res.Total, res.More)
			}
			if want := (1234 + Style.MaxPage - 1) / Style.MaxPage; int(pages.Load()) != want {
				t.Fatalf("%d requests, want %d", pages.Load(), want)
			}
			var first, last struct{ N int }
			_ = json.Unmarshal(res.Items[0], &first)
			_ = json.Unmarshal(res.Items[1233], &last)
			if first.N != 0 || last.N != 1233 {
				t.Fatal("items out of order")
			}
		})
	}
}

func TestPagerNeverLoopsOnARouteThatIgnoresPaging(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
		items := make([]map[string]any, 0, 300)
		for i := 0; i < 300; i++ {
			items = append(items, map[string]any{"n": i})
		}
		_ = json.NewEncoder(w).Encode(items) // everything, whatever was asked
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	res, err := c.List(context.Background(), "/x", nil, Style, 1000)
	if err != nil || len(res.Items) != 300 || n.Load() != 1 {
		t.Fatalf("a route that sends everything at once ends the walk: %v %d %d", err, len(res.Items), n.Load())
	}
	// a route that sends the same full page again is an error and not an endless loop
	srv2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		items := make([]map[string]any, 0, limit)
		for i := 0; i < limit; i++ {
			items = append(items, map[string]any{"n": i})
		}
		_ = json.NewEncoder(w).Encode(items)
	}))
	defer srv2.Close()
	c, _ = toolClient(srv2.URL)
	if _, err := c.List(context.Background(), "/x", nil, Style, 1000); err == nil || !strings.Contains(err.Error(), "ignored its paging parameters") {
		t.Fatalf("%v", err)
	}
}

func TestPagerStopsAtTheLimitAndSaysThereIsMore(t *testing.T) {
	srv, pages := listServer(t, 1234, "offset", 200, true)
	c, _ := toolClient(srv.URL)
	res, err := c.List(context.Background(), "/x", nil, Style, 250)
	if err != nil || len(res.Items) != 250 || !res.More || res.Total != 1234 {
		t.Fatalf("%v %d %v %d", err, len(res.Items), res.More, res.Total)
	}
	if pages.Load() != 2 {
		t.Fatalf("a limit of 250 needs 2 pages, used %d", pages.Load())
	}
}

func TestPagerWithoutATotalStopsOnAShortPageAndGuessesAtTheLimit(t *testing.T) {
	srv, _ := listServer(t, 90, "offset", 200, false)
	c, _ := toolClient(srv.URL)
	res, _ := c.List(context.Background(), "/x", nil, Style, 1000)
	if len(res.Items) != 90 || res.Total != -1 || res.More {
		t.Fatalf("%d %d %v", len(res.Items), res.Total, res.More)
	}
	res, _ = c.List(context.Background(), "/x", nil, Style, 90)
	if len(res.Items) != 90 || !res.More {
		t.Fatalf("a full page at the limit may have more behind it: %v", res.More)
	}
}

func TestPagerKeepsFiltersAndRefusesHugeLimitsAndNonLists(t *testing.T) {
	var seen string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.Query().Get("status")
		_, _ = w.Write([]byte(`{"not":"a list"}`))
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	_, err := c.List(context.Background(), "/x", map[string][]string{"status": {"open"}}, Style, 10)
	if seen != "open" || err == nil || !strings.Contains(err.Error(), "not a list") {
		t.Fatalf("%q %v", seen, err)
	}
	if _, err := c.List(context.Background(), "/x", nil, Style, MaxListLimit+1); err == nil {
		t.Fatal("a limit above the maximum must be refused")
	}
}

func TestPagerStopsOnAnErrorAndReturnsIt(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if n.Add(1) == 2 {
			w.WriteHeader(404)
			_, _ = w.Write([]byte(`{"detail":"gone"}`))
			return
		}
		_, _ = w.Write([]byte(fmt.Sprintf("[%s]", strings.TrimSuffix(strings.Repeat(`{"a":1},`, 200), ","))))
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	_, err := c.List(context.Background(), "/x", nil, Style, 1000)
	var e *Error
	if !errors.As(err, &e) || e.Status != 404 || e.Message != "gone" {
		t.Fatalf("%v", err)
	}
}

// ---- the retry rules, with a fake clock ----

func TestGETRetriesNetworkFailuresWithGrowingWaitsThenGivesUp(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	srv.Close() // a dead address: every try fails
	c, clock := toolClient(srv.URL)
	_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
	var e *Error
	if !errors.As(err, &e) || e.Status != 0 {
		t.Fatalf("%v", err)
	}
	want := []time.Duration{500 * time.Millisecond, time.Second, 2 * time.Second}
	if fmt.Sprint(clock.sleeps) != fmt.Sprint(want) {
		t.Fatalf("waits %v, want %v (4 tries in all)", clock.sleeps, want)
	}
}

func TestBackoffIsCapped(t *testing.T) {
	p := RetryPolicy{MaxAttempts: 20, BaseDelay: time.Second, MaxDelay: 8 * time.Second}
	for attempt := 0; attempt < 19; attempt++ {
		_, wait, _ := p.decide(Request{Method: "GET"}, 503, "", nil, attempt, 0)
		if wait > 8*time.Second || wait < time.Second {
			t.Fatalf("attempt %d waits %v", attempt, wait)
		}
	}
}

func TestGatewayErrorsAreRetriedAndOthersAreNot(t *testing.T) {
	for _, status := range []int{502, 503, 504} {
		var n atomic.Int32
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if n.Add(1) < 3 {
				w.WriteHeader(status)
				return
			}
			_, _ = w.Write([]byte(`{}`))
		}))
		c, clock := toolClient(srv.URL)
		if _, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"}); err != nil {
			t.Fatalf("%d: %v", status, err)
		}
		if n.Load() != 3 || len(clock.sleeps) != 2 {
			t.Fatalf("%d: %d tries, waits %v", status, n.Load(), clock.sleeps)
		}
		srv.Close()
	}
	for _, status := range []int{400, 401, 403, 404, 409, 422, 500, 501} {
		var n atomic.Int32
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { n.Add(1); w.WriteHeader(status) }))
		c, clock := toolClient(srv.URL)
		_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
		if n.Load() != 1 || len(clock.sleeps) != 0 {
			t.Fatalf("%d must not be retried: %d tries", status, n.Load())
		}
		srv.Close()
	}
}

func TestA429WaitsForRetryAfterForAnyMethodAndGivesUpAfterThree(t *testing.T) {
	for _, method := range []string{"GET", "POST", "PATCH", "DELETE"} {
		var n atomic.Int32
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			n.Add(1)
			w.Header().Set("Retry-After", "7")
			w.WriteHeader(429)
			_, _ = w.Write([]byte(`{"detail":"slow down"}`))
		}))
		c, clock := toolClient(srv.URL)
		_, err := c.Do(context.Background(), Request{Method: method, Path: "/x"})
		var e *Error
		if !errors.As(err, &e) || e.Status != 429 || e.RetryAfter != 7*time.Second {
			t.Fatalf("%s: %v", method, err)
		}
		if n.Load() != 4 || len(clock.sleeps) != 3 || clock.sleeps[0] != 7*time.Second {
			t.Fatalf("%s: %d tries, waits %v (a 429 means nothing was done, so any request may wait)", method, n.Load(), clock.sleeps)
		}
		srv.Close()
	}
}

func TestA429WithoutRetryAfterUsesTheDefaultAndOneTooLongIsNotWaitedOut(t *testing.T) {
	var header = ""
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if n.Add(1) == 1 && header != "" {
			w.Header().Set("Retry-After", header)
		}
		if n.Load() == 1 {
			w.WriteHeader(429)
			return
		}
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	c, clock := toolClient(srv.URL)
	if _, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"}); err != nil || clock.sleeps[0] != 10*time.Second {
		t.Fatalf("default wait: %v %v", err, clock.sleeps)
	}
	for _, long := range []string{"61", "3600", "99999999"} {
		header, n = long, atomic.Int32{}
		c, clock = toolClient(srv.URL)
		_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
		var e *Error
		if !errors.As(err, &e) || e.Status != 429 || len(clock.sleeps) != 0 {
			t.Fatalf("Retry-After %s: %v %v", long, err, clock.sleeps)
		}
	}
	// the date form is not read, so the default applies
	header, n = "Wed, 21 Oct 2026 07:28:00 GMT", atomic.Int32{}
	c, clock = toolClient(srv.URL)
	if _, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"}); err != nil || clock.sleeps[0] != 10*time.Second {
		t.Fatalf("%v %v", err, clock.sleeps)
	}
}

func TestWritesAreNeverRetriedAfterAFailureUnlessMarkedSafe(t *testing.T) {
	for _, status := range []int{502, 503, 504} {
		for _, tc := range []struct {
			idempotent bool
			tries      int32
		}{{false, 1}, {true, 4}} {
			var n atomic.Int32
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { n.Add(1); w.WriteHeader(status) }))
			c, _ := toolClient(srv.URL)
			_, _ = c.Do(context.Background(), Request{Method: "PATCH", Path: "/x", Idempotent: tc.idempotent})
			if n.Load() != tc.tries {
				t.Fatalf("%d idempotent=%v: %d tries, want %d", status, tc.idempotent, n.Load(), tc.tries)
			}
			srv.Close()
		}
	}
	// and not after a network failure
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	srv.Close()
	c, clock := toolClient(srv.URL)
	_, _ = c.Do(context.Background(), Request{Method: "POST", Path: "/x", Body: map[string]any{}})
	if len(clock.sleeps) != 0 {
		t.Fatalf("a write retried after a network failure: %v", clock.sleeps)
	}
}

func TestNoRetryAndNoRetryPolicyAreHonoured(t *testing.T) {
	var n atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { n.Add(1); w.WriteHeader(503) }))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/x", NoRetry: true})
	c.Retry = NoRetry
	_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
	if n.Load() != 2 {
		t.Fatalf("%d tries", n.Load())
	}
}

func TestACertificateFailureIsNeverRetried(t *testing.T) {
	var reached atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { reached.Add(1) }))
	defer srv.Close()
	c, clock := toolClient(srv.URL)
	_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
	if err == nil || len(clock.sleeps) != 0 || reached.Load() != 0 {
		t.Fatalf("%v %v %d", err, clock.sleeps, reached.Load())
	}
	var cert *tls.CertificateVerificationError
	if !isCertificateError(err.(*Error).Err) && !errors.As(err, &cert) && !strings.Contains(err.Error(), "certificate") {
		t.Fatalf("not recognised as a certificate failure: %v", err)
	}
}

func TestACancelledContextStopsTheRetries(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	srv.Close()
	c, _ := toolClient(srv.URL)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.Do(ctx, Request{Method: "GET", Path: "/x"}); err == nil {
		t.Fatal("expected an error")
	}
}

// ---- the error type and the token ----

func TestErrorCarriesStatusAndTheServersOwnMessage(t *testing.T) {
	for body, want := range map[string]string{
		`{"detail":"Device not found"}`:                                          "Device not found",
		`{"detail":[{"loc":["query","limit"],"msg":"too big"}]}`:                 "query.limit: too big",
		`{"detail":[{"loc":[],"msg":"bad"},{"loc":["body","x"],"msg":"worse"}]}`: "bad; body.x: worse",
		`plain words`: "plain words",
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404); _, _ = w.Write([]byte(body)) }))
		c, _ := toolClient(srv.URL)
		_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
		var e *Error
		if !errors.As(err, &e) || e.Status != 404 || e.Message != want || e.Path != "/x" || e.Method != "GET" {
			t.Fatalf("%q: %#v", body, err)
		}
		srv.Close()
	}
}

func TestTokenIsSentAsBearerAndNeverWithTheDeviceKey(t *testing.T) {
	var auth, key string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth, key = r.Header.Get("Authorization"), r.Header.Get("X-API-Key")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	c.APIKey = "device-key"
	_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
	if auth != "Bearer "+c.Token || key != "" {
		t.Fatalf("token request: %q %q", auth, key)
	}
	_, _ = c.Do(context.Background(), Request{Method: "POST", Path: "/x", UseKey: true, Body: map[string]any{}})
	if key != "device-key" || auth != "" {
		t.Fatalf("device request: %q %q", auth, key)
	}
}

func TestSecretsAreBlankedFromEveryErrorEvenWhenTheServerEchoesThem(t *testing.T) {
	const token = "pht_abc123_SECRET-not-real"
	for _, other := range []string{token, "pht_other9_SOMEONEELSESSECRET"} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(400)
			_, _ = w.Write([]byte(`{"detail":"bad ` + other + `"}`))
		}))
		c, _ := toolClient(srv.URL)
		_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
		if err == nil || strings.Contains(err.Error(), "SECRET") || strings.Contains(err.Error(), "pht_") && !strings.Contains(err.Error(), "<token>") {
			t.Fatalf("%v", err)
		}
		srv.Close()
	}
}

func TestTraceSeesMethodPathAndStatusOnly(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{}`)) }))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	var got []string
	c.Trace = func(method, path string, status int, took time.Duration) {
		got = append(got, fmt.Sprint(method, " ", path, " ", status))
	}
	_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/api/v1/x", Query: map[string][]string{"secret": {"q"}}})
	if fmt.Sprint(got) != "[GET /api/v1/x 200]" {
		t.Fatalf("%v", got)
	}
}

func TestWhoamiParsing(t *testing.T) {
	w, err := ParseWhoami([]byte(`{"id":"u1","role":"technician","signed_in_with":"token","token":{"id":"a1b2","name":"ci","scope":"read","expires_at":"2027-01-01T00:00:00Z"}}`))
	if err != nil || w.AccountID != "u1" || w.Role != "technician" || w.SignedIn != "token" || w.TokenID != "a1b2" || w.TokenName != "ci" || w.Scope != "read" || w.ExpiresAt.Year() != 2027 {
		t.Fatalf("%+v %v", w, err)
	}
	w, _ = ParseWhoami([]byte(`{"id":"u1","role":"admin","signed_in_with":"session","token":null}`))
	if w.SignedIn != "session" || w.TokenID != "" || w.Scope != "" {
		t.Fatalf("%+v", w)
	}
}

func TestTimeParsesWhatTheAPIWrites(t *testing.T) {
	for _, text := range []string{`"2026-11-22T12:00:00Z"`, `"2026-11-22T12:00:00+00:00"`, `"2026-11-22T12:00:00.123456+00:00"`, `"2026-11-22T12:00:00"`, `"2026-11-22T12:00:00.5"`, `"2026-11-22"`} {
		var v Time
		if err := json.Unmarshal([]byte(text), &v); err != nil || v.IsZero() || v.Location() != time.UTC {
			t.Fatalf("%s: %v %v", text, v, err)
		}
	}
	var v Time
	if err := json.Unmarshal([]byte(`null`), &v); err != nil || !v.IsZero() {
		t.Fatal("null is the zero time")
	}
	if err := json.Unmarshal([]byte(`"yesterday"`), &v); err == nil {
		t.Fatal("not a time")
	}
}

func TestResolveDeviceByNameAndId(t *testing.T) {
	var queries []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/v1/devices/") {
			_, _ = w.Write([]byte(`{"id":"11111111-1111-4111-8111-111111111111","name":"press-01"}`))
			return
		}
		queries = append(queries, r.URL.RawQuery)
		q := r.URL.Query()
		switch {
		case q.Get("name") == "press-01":
			_, _ = w.Write([]byte(`[{"id":"a","name":"Press-01"},{"id":"c","name":"press-01"}]`))
		case q.Get("name") == "pump":
			_, _ = w.Write([]byte(`[]`))
		case q.Get("search") == "pump":
			_, _ = w.Write([]byte(`[{"id":"p","name":"Pump 1"},{"id":"q","name":"Old pump"}]`))
		case q.Get("name") == "solo":
			_, _ = w.Write([]byte(`[{"id":"s","name":"Solo"}]`))
		default:
			_, _ = w.Write([]byte(`[]`))
		}
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	if d, _, err := c.ResolveDevice(context.Background(), "11111111-1111-4111-8111-111111111111"); err != nil || d.Name != "press-01" {
		t.Fatalf("%v %v", d, err)
	}
	if d, _, err := c.ResolveDevice(context.Background(), "solo"); err != nil || d.ID != "s" {
		t.Fatalf("%v %v", d, err)
	}
	_, _, err := c.ResolveDevice(context.Background(), "press-01")
	var amb *ErrAmbiguous
	if !errors.As(err, &amb) || len(amb.Matches) != 2 {
		t.Fatalf("%v", err)
	}
	_, _, err = c.ResolveDevice(context.Background(), "pump")
	var none *ErrNoMachine
	if !errors.As(err, &none) || fmt.Sprint(none.Similar) != "[Pump 1 Old pump]" || !strings.Contains(err.Error(), "Did you mean: Pump 1, Old pump") {
		t.Fatalf("%v", err)
	}
	if !strings.Contains(queries[0], "name=solo") || strings.Contains(queries[0], "search") {
		t.Fatalf("the name filter is exact and server-side: %s", queries[0])
	}
}

func TestErrorCodeIsReadWhenThereIsOneAndTheStatusStandsAloneWhenNot(t *testing.T) {
	for body, want := range map[string][2]string{
		`{"code":"session_required","detail":"A signed-in session is needed for this.","request_id":"r1"}`:                                  {"A signed-in session is needed for this.", "session_required"},
		`{"code":"validation_failed","detail":"The request is not valid.","errors":[{"loc":["query","limit"],"msg":"too big","type":"x"}]}`: {"The request is not valid.: query.limit: too big", "validation_failed"},
		`{"detail":"Old style"}`:                        {"Old style", ""},
		`{"detail":[{"loc":["body","x"],"msg":"bad"}]}`: {"body.x: bad", ""},
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(403); _, _ = w.Write([]byte(body)) }))
		c, _ := toolClient(srv.URL)
		_, err := c.Do(context.Background(), Request{Method: "GET", Path: "/x"})
		var e *Error
		if !errors.As(err, &e) || e.Message != want[0] || e.Code != want[1] || e.Status != 403 {
			t.Fatalf("%s: %#v", body, e)
		}
		srv.Close()
	}
}

func TestAddressesAreNormalisedAndAPathIsRefused(t *testing.T) {
	for in, want := range map[string]string{"https://a.b": "https://a.b", "https://a.b/": "https://a.b", "https://a.b///": "https://a.b", " https://a.b/ ": "https://a.b"} {
		if got := NormaliseURL(in); got != want {
			t.Fatalf("%q -> %q", in, got)
		}
		if err := CheckURL(in, false); err != nil {
			t.Fatalf("%q: %v", in, err)
		}
		if got := New(in, "").BaseURL; got != want {
			t.Fatalf("New(%q).BaseURL = %q", in, got)
		}
	}
	for _, bad := range []string{"https://a.b/api/v1/telemetry", "https://a.b/api/v1/telemetry/", "https://a.b/x/", "https://a.b/?x=1"} {
		err := CheckURL(bad, false)
		if err == nil || !strings.Contains(err.Error(), "base address only") {
			t.Fatalf("%q: %v", bad, err)
		}
	}
}

func TestServerInfoReadsVersionAndClock(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"version":"2.1.0","updated_at":"2026-11-22T11:59:00+00:00"}`))
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	info, err := c.ServerInfo(context.Background())
	if err != nil || info.Version != "2.1.0" || info.ClockSource != "updated_at" || info.Clock.Minute() != 59 {
		t.Fatalf("%+v %v", info, err)
	}
}

func keysetServer(t *testing.T, total int, withTotal bool) (*httptest.Server, *atomic.Int32, *[]string) {
	var calls atomic.Int32
	queries := []string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		queries = append(queries, r.URL.RawQuery)
		q := r.URL.Query()
		limit, _ := strconv.Atoi(q.Get("limit"))
		start := 0
		if b := q.Get("before"); b != "" {
			start, _ = strconv.Atoi(strings.TrimPrefix(b, "cursor-"))
		} else if o := q.Get("offset"); o != "" {
			start, _ = strconv.Atoi(o)
		}
		end := min(start+limit, total)
		var items []map[string]any
		for i := start; i < end; i++ {
			items = append(items, map[string]any{"n": i})
		}
		if withTotal && q.Get("before") == "" {
			w.Header().Set("X-Total-Count", strconv.Itoa(total))
		}
		if len(items) == limit && end < total {
			w.Header().Set("X-Next-Before", fmt.Sprintf("cursor-%d", end))
		}
		_ = json.NewEncoder(w).Encode(items)
	}))
	t.Cleanup(srv.Close)
	return srv, &calls, &queries
}

func TestKeysetIsUsedWhereTheServerOffersACursorAndOffsetOtherwise(t *testing.T) {
	srv, calls, queries := keysetServer(t, 1234, false)
	c, _ := toolClient(srv.URL)
	res, err := c.List(context.Background(), "/x", nil, Style, 5000)
	if err != nil || len(res.Items) != 1234 || res.Total != -1 || res.More {
		t.Fatalf("%v %d %d %v", err, len(res.Items), res.Total, res.More)
	}
	if calls.Load() != 7 {
		t.Fatalf("%d requests", calls.Load())
	}
	for i, q := range *queries {
		if i == 0 {
			if !strings.Contains(q, "offset=0") {
				t.Fatalf("the first page is read by offset: %s", q)
			}
			continue
		}
		if !strings.Contains(q, "before=cursor-") || strings.Contains(q, "offset=") || strings.Contains(q, "skip=") {
			t.Fatalf("a later page is read by keyset only: %s", q)
		}
	}
	// at the limit with more behind it
	res, err = c.List(context.Background(), "/x", nil, Style, 400)
	if err != nil || len(res.Items) != 400 || !res.More {
		t.Fatalf("%v %d %v", err, len(res.Items), res.More)
	}
	// a list that sends a total on the first page and a cursor after keeps its total
	srv2, _, _ := keysetServer(t, 450, true)
	c2, _ := toolClient(srv2.URL)
	res, err = c2.List(context.Background(), "/x", nil, Style, 1000)
	if err != nil || len(res.Items) != 450 || res.Total != 450 || res.More {
		t.Fatalf("%v %d %d %v", err, len(res.Items), res.Total, res.More)
	}
}

func TestReadingsGiveTheNextCursorAndSendNoTotalRequest(t *testing.T) {
	srv, _, queries := keysetServer(t, 800, false)
	c, _ := toolClient(srv.URL)
	rows, next, err := c.Readings(context.Background(), "d1", ReadingsOptions{Limit: 500})
	if err != nil || len(rows) != 500 || next != "cursor-500" {
		t.Fatalf("%v %d %q", err, len(rows), next)
	}
	rows, next, err = c.Readings(context.Background(), "d1", ReadingsOptions{Limit: 500, Before: next})
	if err != nil || len(rows) != 300 || next != "" {
		t.Fatalf("a short page is the end: %v %d %q", err, len(rows), next)
	}
	if q := (*queries)[1]; !strings.Contains(q, "before=cursor-500") || strings.Contains(q, "offset") {
		t.Fatalf("%s", q)
	}
}

func TestDeprecationHeadersReachTheCallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Deprecation", "true")
		w.Header().Set("Sunset", "Wed, 01 Jul 2027 00:00:00 GMT")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	c, _ := toolClient(srv.URL)
	var got []string
	c.OnDeprecated = func(m, p, s string) { got = append(got, m+" "+p+" "+s) }
	_, _ = c.Do(context.Background(), Request{Method: "GET", Path: "/old"})
	if fmt.Sprint(got) != "[GET /old Wed, 01 Jul 2027 00:00:00 GMT]" {
		t.Fatalf("%v", got)
	}
}
