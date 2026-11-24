package api

import (
	"encoding/json"
	"strings"
	"time"
)

// Time is a time the API wrote. It reads RFC 3339 and also the form with no zone, which is UTC.
type Time struct{ time.Time }

func (t *Time) UnmarshalJSON(data []byte) error {
	text := strings.Trim(string(data), `"`)
	if text == "null" || text == "" {
		return nil
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02T15:04:05", "2006-01-02"} {
		if parsed, err := time.Parse(layout, text); err == nil {
			t.Time = parsed.UTC()
			return nil
		}
	}
	return &time.ParseError{Value: text, Message: ": not a time"}
}

func (t Time) IsZero() bool { return t.Time.IsZero() }

// ModelStatus is the anomaly model's state for one machine.
type ModelStatus struct {
	State              string   `json:"state"`
	Scope              *string  `json:"scope"`
	HoursCollected     *float64 `json:"hours_collected"`
	HoursNeeded        *float64 `json:"hours_needed"`
	FalseAlertsPerWeek *float64 `json:"false_alerts_per_week"`
	TrainedAt          Time     `json:"trained_at"`
}

// Device is a machine.
type Device struct {
	ID                   string       `json:"id"`
	Name                 string       `json:"name"`
	Location             *string      `json:"location"`
	Type                 *string      `json:"type"`
	Status               string       `json:"status"`
	LastSeen             Time         `json:"last_seen"`
	FirmwareVersion      *string      `json:"firmware_version"`
	OwnerName            *string      `json:"owner_name"`
	Tags                 []string     `json:"tags"`
	ExpectedIntervalS    int          `json:"expected_interval_s"`
	LinkState            string       `json:"link_state"`
	SecondsSinceLastPost *int64       `json:"seconds_since_last_post"`
	Model                *ModelStatus `json:"model"`
	ReplayProtected      bool         `json:"replay_protected"`
	LastBoot             *int64       `json:"last_boot"`
	LastSeq              *int64       `json:"last_seq"`
	ReplayRefused        int          `json:"replay_refused"`
	ReplayStatus         *string      `json:"replay_status"`
	ReplayWarning        *string      `json:"replay_warning"`
}

// Alert is one alert.
type Alert struct {
	ID          string   `json:"id"`
	DeviceID    string   `json:"device_id"`
	Message     *string  `json:"message"`
	Severity    *string  `json:"severity"`
	Resolved    bool     `json:"resolved"`
	TriggeredAt Time     `json:"triggered_at"`
	ResolvedAt  Time     `json:"resolved_at"`
	Category    string   `json:"category"`
	Kind        *string  `json:"kind"`
	SensorKey   *string  `json:"sensor_key"`
	Occurrences int      `json:"occurrences"`
	LastValue   *float64 `json:"last_value"`
	PeakValue   *float64 `json:"peak_value"`
}

// Ticket is a maintenance ticket.
type Ticket struct {
	ID             string  `json:"id"`
	DeviceID       *string `json:"device_id"`
	AlertID        *string `json:"alert_id"`
	Title          *string `json:"title"`
	Description    *string `json:"description"`
	Status         string  `json:"status"`
	Priority       *string `json:"priority"`
	AssignedToName *string `json:"assigned_to_name"`
	CreatedByName  *string `json:"created_by_name"`
	CreatedAt      Time    `json:"created_at"`
	UpdatedAt      Time    `json:"updated_at"`
	TicketNumber   *int    `json:"ticket_number"`
}

// Reading is one telemetry row. The row has dozens of columns that depend on the node, so the
// columns are kept as a map.
type Reading struct {
	ID         string
	DeviceID   string
	RecordedAt Time
	NodeType   string
	Fields     map[string]any
}

func (r *Reading) UnmarshalJSON(data []byte) error {
	if err := json.Unmarshal(data, &r.Fields); err != nil {
		return err
	}
	r.ID, _ = r.Fields["id"].(string)
	r.DeviceID, _ = r.Fields["device_id"].(string)
	r.NodeType, _ = r.Fields["node_type"].(string)
	if text, ok := r.Fields["recorded_at"].(string); ok {
		quoted, _ := json.Marshal(text)
		_ = r.RecordedAt.UnmarshalJSON(quoted)
	}
	return nil
}

// HealthSummary is the fleet summary.
type HealthSummary struct {
	TotalDevices int            `json:"total_devices"`
	Online       int            `json:"online"`
	Offline      int            `json:"offline"`
	LinkStates   map[string]int `json:"link_states"`
	ActiveAlerts int            `json:"active_alerts"`
	OpenTickets  int            `json:"open_tickets"`
	HealthScore  int            `json:"health_score"`
}

// MLStatus is what is in service and the outcome of the latest retrain.
type MLStatus struct {
	State     string `json:"state"`
	TrainedAt Time   `json:"trained_at"`
	Models    []struct {
		Key                string   `json:"key"`
		Scope              string   `json:"scope"`
		Legacy             bool     `json:"legacy"`
		FalseAlertsPerWeek *float64 `json:"false_alerts_per_week"`
	} `json:"models"`
	LastRetrain *struct {
		Status     string `json:"status"`
		FinishedAt Time   `json:"finished_at"`
		Summary    string `json:"summary"`
		Trigger    string `json:"trigger"`
	} `json:"last_retrain"`
	Schedule struct {
		NightlyUTC string `json:"nightly_utc"`
		NextAt     Time   `json:"next_at"`
	} `json:"schedule"`
}

// Whoami says who a request is: the account's id and role, how the caller signed in (session or token)
// and, for a token, its id, name, scope and expiry.
type Whoami struct {
	AccountID string
	Role      string
	SignedIn  string
	TokenID   string
	TokenName string
	Scope     string
	ExpiresAt Time
}

// ParseWhoami reads a whoami reply: {"id", "role", "signed_in_with", "token": null | {...}}.
func ParseWhoami(data []byte) (Whoami, error) {
	var body struct {
		ID           string `json:"id"`
		Role         string `json:"role"`
		SignedInWith string `json:"signed_in_with"`
		Token        *struct {
			ID        string `json:"id"`
			Name      string `json:"name"`
			Scope     string `json:"scope"`
			ExpiresAt Time   `json:"expires_at"`
		} `json:"token"`
	}
	if err := json.Unmarshal(data, &body); err != nil {
		return Whoami{}, err
	}
	w := Whoami{AccountID: body.ID, Role: body.Role, SignedIn: body.SignedInWith}
	if body.Token != nil {
		w.TokenID, w.TokenName, w.Scope, w.ExpiresAt = body.Token.ID, body.Token.Name, body.Token.Scope, body.Token.ExpiresAt
		if w.SignedIn == "" {
			w.SignedIn = "token"
		}
	}
	return w, nil
}

// TokenInfo is one entry of GET /auth/tokens.
type TokenInfo struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Scope      string `json:"scope"`
	CreatedAt  Time   `json:"created_at"`
	ExpiresAt  Time   `json:"expires_at"`
	LastUsedAt Time   `json:"last_used_at"`
}
