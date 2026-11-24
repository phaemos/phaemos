package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestSendReadingUsesDeviceKey(t *testing.T) {
	var gotKey, gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey, gotPath = r.Header.Get("X-API-Key"), r.URL.Path
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]any{"is_anomaly": true, "anomaly_score": 0.91})
	}))
	defer server.Close()

	stored, err := New(server.URL, "key-123").SendReading(context.Background(), map[string]any{"device_id": "d1"})
	if err != nil {
		t.Fatal(err)
	}
	if gotKey != "key-123" || gotPath != "/api/v1/telemetry" {
		t.Fatalf("got key %q path %q", gotKey, gotPath)
	}
	if stored["is_anomaly"] != true {
		t.Fatalf("unexpected response %v", stored)
	}
}

func TestErrorsIncludeStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"detail":"Invalid API key"}`, http.StatusUnauthorized)
	}))
	defer server.Close()

	if _, err := New(server.URL, "bad").SendReading(context.Background(), map[string]any{}); err == nil {
		t.Fatal("expected an error for a 401")
	}
}

func TestErrorTextIsCapped(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(strings.Repeat("x", 5<<20)))
	}))
	defer server.Close()

	_, err := New(server.URL, "k").SendReading(context.Background(), map[string]any{})
	if err == nil {
		t.Fatal("expected an error")
	}
	if len(err.Error()) > 300 {
		t.Fatalf("error text is %d bytes, want at most 300", len(err.Error()))
	}
	if !strings.Contains(err.Error(), "400") || !strings.Contains(err.Error(), "(cut)") {
		t.Fatalf("unexpected error %q", err)
	}
}

func TestErrorTextHidesKeyAndControlCharacters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte("bad key secret-key-1\x1b[31m\x00 end"))
	}))
	defer server.Close()

	_, err := New(server.URL, "secret-key-1").SendReading(context.Background(), map[string]any{})
	if err == nil {
		t.Fatal("expected an error")
	}
	text := err.Error()
	if strings.Contains(text, "secret-key-1") || strings.ContainsAny(text, "\x1b\x00") {
		t.Fatalf("error text leaks or is not clean: %q", text)
	}
}

func TestRedirectIsNotFollowedAndKeyNotResent(t *testing.T) {
	var elsewhereKey string
	elsewhere := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		elsewhereKey = r.Header.Get("X-API-Key")
		w.WriteHeader(http.StatusCreated)
	}))
	defer elsewhere.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, elsewhere.URL+"/x", http.StatusTemporaryRedirect)
	}))
	defer server.Close()

	if _, err := New(server.URL, "k").SendReading(context.Background(), map[string]any{}); err == nil {
		t.Fatal("expected an error for a redirect")
	}
	if elsewhereKey != "" {
		t.Fatalf("the key was sent on to another address: %q", elsewhereKey)
	}
}

func TestSuccessfulReplyIsBoundedAndValidJSONIsCutNotRead(t *testing.T) {
	// a reply that is valid JSON only if all of it is read: a 5 MiB string. With the cap the body is
	// cut, so it no longer parses. Without the cap it would parse and the client would hold 5 MiB.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"a":"` + strings.Repeat("y", 5<<20) + `"}`))
	}))
	defer server.Close()

	if _, err := New(server.URL, "k").Status(context.Background()); err == nil {
		t.Fatal("expected a parse error for a reply cut at the cap")
	}
}

func TestReplyJustUnderTheCapIsStillRead(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"a":"` + strings.Repeat("y", maxReplyBytes-20) + `"}`))
	}))
	defer server.Close()

	if _, err := New(server.URL, "k").Status(context.Background()); err != nil {
		t.Fatalf("a reply under the cap must be read: %v", err)
	}
}

func TestCertificatesAreChecked(t *testing.T) {
	// httptest's TLS server uses a certificate no default trust store knows. A client that verifies
	// must refuse it. One with InsecureSkipVerify would accept it, so this fails if checking is off.
	var reached bool
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reached = true
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	if _, err := New(server.URL, "k").Status(context.Background()); err == nil {
		t.Fatal("expected a certificate error")
	}
	if reached {
		t.Fatal("the request reached a server whose certificate is not trusted")
	}
}

func TestOtherFailuresNeverHoldTheKey(t *testing.T) {
	const key = "secret-key-777"
	cases := map[string]http.HandlerFunc{
		"401 echo": func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(401)
			_, _ = w.Write([]byte("bad " + r.Header.Get("X-API-Key")))
		},
		"409": func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(409) },
		"500 header echo": func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(500)
			_, _ = w.Write([]byte(strings.Repeat("k", 10) + r.Header.Get("X-API-Key")))
		},
		"bad json": func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte("not json " + r.Header.Get("X-API-Key")))
		},
	}
	for name, handler := range cases {
		server := httptest.NewServer(handler)
		_, err := New(server.URL, key).SendReading(context.Background(), map[string]any{})
		server.Close()
		if err == nil {
			t.Fatalf("%s: expected an error", name)
		}
		if strings.Contains(err.Error(), key) {
			t.Fatalf("%s: error holds the key: %v", name, err)
		}
	}
	// a connection that fails
	if _, err := New("http://127.0.0.1:1", key).Status(context.Background()); err == nil || strings.Contains(err.Error(), key) {
		t.Fatalf("connection error: %v", err)
	}
}

func TestConflictIsACounterRefusalAndDuplicateIsDelivered(t *testing.T) {
	status := http.StatusConflict
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if status == http.StatusConflict {
			w.WriteHeader(status)
			return
		}
		_, _ = w.Write([]byte(`{"status":"duplicate","stored":false,"detail":"x"}`))
	}))
	defer server.Close()
	c := New(server.URL, "k")
	if _, err := c.SendReading(context.Background(), map[string]any{}); !errors.Is(err, ErrCounterRefused) {
		t.Fatalf("expected ErrCounterRefused, got %v", err)
	}
	status = http.StatusOK
	reply, err := c.SendReading(context.Background(), map[string]any{})
	if err != nil || !IsDuplicate(reply) {
		t.Fatalf("a duplicate answer is a delivered post: %v %v", reply, err)
	}
}

func TestReadingsCarryBootSeqAndUpAndSeqRises(t *testing.T) {
	var bodies []map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m map[string]any
		_ = json.NewDecoder(r.Body).Decode(&m)
		bodies = append(bodies, m)
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{}`))
	}))
	defer server.Close()
	c := New(server.URL, "key-1")
	c.Counter = NewCounter(t.TempDir(), "key-1", time.Unix(1800000000, 0))
	for i := 0; i < 3; i++ {
		if _, err := c.SendReading(context.Background(), map[string]any{"device_id": "d"}); err != nil {
			t.Fatal(err)
		}
	}
	for i, b := range bodies {
		if b["boot"] != float64(1800000000) || b["seq"] != float64(i) {
			t.Fatalf("post %d: %v", i, b)
		}
		if _, ok := b["up"]; !ok {
			t.Fatalf("post %d has no up", i)
		}
	}
}

func TestCheckURL(t *testing.T) {
	good := []string{"https://api.example.org", "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"}
	for _, raw := range good {
		if err := CheckURL(raw, false); err != nil {
			t.Errorf("%s: %v", raw, err)
		}
	}
	bad := []string{"http://dev.localhost:8000", "http://localhost.example.org", "http://192.168.1.5:8000", "http://api.example.org", "ftp://x", "api.example.org", "https://u:p@h", "https://"}
	for _, raw := range bad {
		if err := CheckURL(raw, false); err == nil {
			t.Errorf("%s: expected an error", raw)
		}
	}
	if err := CheckURL("http://192.168.1.5:8000", true); err != nil {
		t.Errorf("flag should allow plain http: %v", err)
	}
}
