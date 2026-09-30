package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
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
