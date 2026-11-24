package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// IsUUID reports whether text looks like an id.
func IsUUID(text string) bool { return uuidPattern.MatchString(text) }

func (c *Client) get(ctx context.Context, path string, q url.Values) (*Response, error) {
	return c.Do(ctx, Request{Method: http.MethodGet, Path: path, Query: q})
}

// StatusRaw calls the public status route and returns the server's own JSON.
func (c *Client) StatusRaw(ctx context.Context) ([]byte, error) {
	resp, err := c.get(ctx, "/status", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// WhoamiRaw calls whoami and returns the server's JSON.
func (c *Client) WhoamiRaw(ctx context.Context) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/auth/whoami", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// TokensRaw lists the account's unrevoked tokens, newest first. A token may read this list but never
// change it.
func (c *Client) TokensRaw(ctx context.Context) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/tokens", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// HealthRaw returns the fleet summary as the server wrote it.
func (c *Client) HealthRaw(ctx context.Context) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/health/summary", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// ModelRaw returns the anomaly model's status as the server wrote it.
func (c *Client) ModelRaw(ctx context.Context) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/ml/status", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// ServerVersion asks the interactive docs' schema for the version. A production server turns the docs
// off, so an empty answer is normal.
func (c *Client) ServerVersion(ctx context.Context) string {
	resp, err := c.Do(ctx, Request{Method: http.MethodGet, Path: "/openapi.json", NoRetry: true})
	if err != nil {
		return ""
	}
	var doc struct {
		Info struct {
			Version string `json:"version"`
		} `json:"info"`
	}
	if json.Unmarshal(resp.Body, &doc) != nil {
		return ""
	}
	return doc.Info.Version
}

// ListDevices pages through the machines the caller may read.
func (c *Client) ListDevices(ctx context.Context, search, status, tag string, limit int) (*ListResult, error) {
	return c.listDevices(ctx, "", search, status, tag, limit)
}

func (c *Client) listDevices(ctx context.Context, name, search, status, tag string, limit int) (*ListResult, error) {
	q := url.Values{}
	if name != "" {
		q.Set("name", name)
	}
	if search != "" {
		q.Set("search", search)
	}
	if status != "" {
		q.Set("status", status)
	}
	if tag != "" {
		q.Set("tag", tag)
	}
	return c.List(ctx, "/api/v1/devices", q, Style, limit)
}

// ErrAmbiguous is returned when a name matches more than one machine.
type ErrAmbiguous struct {
	Ref     string
	Matches []string
}

func (e *ErrAmbiguous) Error() string {
	return fmt.Sprintf("%q matches %d machines (%s): use the id", e.Ref, len(e.Matches), strings.Join(e.Matches, ", "))
}

// ErrNoMachine is returned when no machine has that name.
type ErrNoMachine struct {
	Ref     string
	Similar []string
}

func (e *ErrNoMachine) Error() string {
	if len(e.Similar) == 0 {
		return fmt.Sprintf("no device is called %q", e.Ref)
	}
	return fmt.Sprintf("no device is called %q. Did you mean: %s", e.Ref, strings.Join(e.Similar, ", "))
}

// ResolveDevice finds a device by id or by name. A name is looked up with the server's exact, case-insensitive
// `name` filter, so the fleet is not paged through. When nothing matches, the contains-match `search` is asked for
// names to suggest.
func (c *Client) ResolveDevice(ctx context.Context, ref string) (Device, json.RawMessage, error) {
	if IsUUID(ref) {
		resp, err := c.get(ctx, "/api/v1/devices/"+ref, nil)
		if err != nil {
			return Device{}, nil, err
		}
		var d Device
		if err := json.Unmarshal(resp.Body, &d); err != nil {
			return Device{}, nil, err
		}
		return d, resp.Body, nil
	}
	found, err := c.listDevices(ctx, ref, "", "", "", 50)
	if err != nil {
		return Device{}, nil, err
	}
	devices, err := DecodeAll[Device](found.Items)
	if err != nil {
		return Device{}, nil, err
	}
	switch len(devices) {
	case 0:
		var similar []string
		if close, err := c.listDevices(ctx, "", ref, "", "", 5); err == nil {
			if ds, err := DecodeAll[Device](close.Items); err == nil {
				for _, d := range ds {
					similar = append(similar, d.Name)
				}
			}
		}
		return Device{}, nil, &ErrNoMachine{Ref: ref, Similar: similar}
	case 1:
		return devices[0], found.Items[0], nil
	}
	ids := make([]string, 0, len(devices))
	for _, d := range devices {
		ids = append(ids, d.ID)
	}
	return Device{}, nil, &ErrAmbiguous{Ref: ref, Matches: ids}
}

// AlertFilter holds the filters the server applies to GET /alerts.
type AlertFilter struct {
	DeviceID string
	OpenOnly bool
	Category string
	Severity string
	Kind     string
}

// ListAlerts pages through alerts. Every filter is the server's own.
func (c *Client) ListAlerts(ctx context.Context, f AlertFilter, limit int) (*ListResult, error) {
	q := url.Values{}
	if f.DeviceID != "" {
		q.Set("device_id", f.DeviceID)
	}
	if f.OpenOnly {
		q.Set("resolved", "false")
	}
	if f.Category != "" {
		q.Set("category", f.Category)
	}
	if f.Severity != "" {
		q.Set("severity", f.Severity)
	}
	if f.Kind != "" {
		q.Set("kind", f.Kind)
	}
	return c.List(ctx, "/api/v1/alerts", q, Style, limit)
}

// GetAlertRaw reads one alert by id.
func (c *Client) GetAlertRaw(ctx context.Context, id string) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/alerts/"+url.PathEscape(id), nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// ListWindows pages through maintenance windows.
func (c *Client) ListWindows(ctx context.Context, limit int) (*ListResult, error) {
	return c.List(ctx, "/api/v1/maintenance-windows", nil, Style, limit)
}

// CreateWindow starts a maintenance window. It needs the admin scope.
func (c *Client) CreateWindow(ctx context.Context, label string, start, end time.Time, deviceID, idempotencyKey string) ([]byte, error) {
	body := map[string]any{"label": label, "start_at": start.UTC().Format(time.RFC3339), "end_at": end.UTC().Format(time.RFC3339), "suppress_alerts": true, "device_id": nil}
	if deviceID != "" {
		body["device_id"] = deviceID
	}
	// with an Idempotency-Key a repeat after a time-out returns the first answer and creates nothing, so the
	// create is safe to retry
	req := Request{Method: http.MethodPost, Path: "/api/v1/maintenance-windows", Body: body}
	if idempotencyKey != "" {
		req.Headers = map[string]string{"Idempotency-Key": idempotencyKey}
		req.Idempotent = true
	}
	resp, err := c.Do(ctx, req)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// EndWindow ends a maintenance window now by moving its end to the given time. Repeating it is safe.
func (c *Client) EndWindow(ctx context.Context, id string, now time.Time) ([]byte, error) {
	resp, err := c.Do(ctx, Request{Method: http.MethodPatch, Path: "/api/v1/maintenance-windows/" + url.PathEscape(id), Body: map[string]any{"end_at": now.UTC().Format(time.RFC3339)}, Idempotent: true})
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// AcceptCounter accepts a new (boot, seq) counter for a device whose flash was wiped. It needs the admin
// scope. Repeating it is safe: it forgets the last pair and the next post sets the new start.
func (c *Client) AcceptCounter(ctx context.Context, deviceID string) ([]byte, error) {
	resp, err := c.Do(ctx, Request{Method: http.MethodPost, Path: "/api/v1/devices/" + url.PathEscape(deviceID) + "/accept-counter", Idempotent: true})
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// RevokeCurrentToken revokes the token making the request. A token may revoke itself and nothing else.
// Repeating it is not needed: a revoked token is refused.
func (c *Client) RevokeCurrentToken(ctx context.Context) error {
	_, err := c.Do(ctx, Request{Method: http.MethodDelete, Path: "/api/v1/tokens/current"})
	return err
}

// ServerInfo is what the public status route says about the server and its clock.
type ServerInfo struct {
	Version string
	// Clock is the server's own time (updated_at of /status) when it sent one, else its Date header.
	Clock       time.Time
	ClockSource string
}

// ServerInfo reads /status for the server's version and clock.
func (c *Client) ServerInfo(ctx context.Context) (ServerInfo, error) {
	resp, err := c.get(ctx, "/status", nil)
	if err != nil {
		return ServerInfo{}, err
	}
	var body struct {
		Version   string `json:"version"`
		UpdatedAt Time   `json:"updated_at"`
	}
	_ = json.Unmarshal(resp.Body, &body)
	info := ServerInfo{Version: body.Version}
	if !body.UpdatedAt.IsZero() {
		info.Clock, info.ClockSource = body.UpdatedAt.Time, "updated_at"
	} else if date, err := http.ParseTime(resp.Header.Get("Date")); err == nil {
		info.Clock, info.ClockSource = date, "Date header"
	}
	return info, nil
}

// ResolveAlert marks an alert resolved (POST: an action is a POST and the PATCH form is a deprecated alias). Repeating it is safe: an alert that is already resolved stays
// resolved, so it is retried after a network failure.
func (c *Client) ResolveAlert(ctx context.Context, id string) ([]byte, error) {
	resp, err := c.Do(ctx, Request{Method: http.MethodPost, Path: "/api/v1/alerts/" + url.PathEscape(id) + "/resolve", Idempotent: true})
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// ListTickets pages through tickets.
func (c *Client) ListTickets(ctx context.Context, status, priority, alertID string, limit int) (*ListResult, error) {
	return c.ListTicketsFor(ctx, TicketFilter{Status: status, Priority: priority, AlertID: alertID}, limit)
}

// TicketFilter holds the filters the server applies to GET /tickets.
type TicketFilter struct {
	Status, Priority, AlertID, DeviceID string
	// Number is the ticket's own number (PHM-0012 is 12). Zero means any.
	Number int
}

// ListTicketsFor pages through tickets with the server's filters.
func (c *Client) ListTicketsFor(ctx context.Context, f TicketFilter, limit int) (*ListResult, error) {
	status, priority, alertID := f.Status, f.Priority, f.AlertID
	q := url.Values{}
	if f.DeviceID != "" {
		q.Set("device_id", f.DeviceID)
	}
	if f.Number > 0 {
		q.Set("ticket_number", strconv.Itoa(f.Number))
	}
	if status != "" {
		q.Set("status", status)
	}
	if priority != "" {
		q.Set("priority", priority)
	}
	if alertID != "" {
		q.Set("alert_id", alertID)
	}
	return c.List(ctx, "/api/v1/tickets", q, Style, limit)
}

// GetTicketRaw reads one ticket.
func (c *Client) GetTicketRaw(ctx context.Context, id string) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/tickets/"+url.PathEscape(id), nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// LatestReadingRaw reads a machine's newest reading.
func (c *Client) LatestReadingRaw(ctx context.Context, deviceID string) ([]byte, error) {
	resp, err := c.get(ctx, "/api/v1/telemetry/"+deviceID+"/latest", nil)
	if err != nil {
		return nil, err
	}
	return resp.Body, nil
}

// ReadingsOptions selects raw readings. The route returns newest first.
type ReadingsOptions struct {
	Limit  int
	Offset int
	// Before is a keyset cursor (from X-Next-Before) and replaces Offset.
	Before string
	From   time.Time
	To     time.Time
}

// Readings reads one page of raw readings, newest first. The route sends no total, on purpose. A full page
// carries the cursor of its last row in next: send it back as Before until a page comes back short.
func (c *Client) Readings(ctx context.Context, deviceID string, o ReadingsOptions) (rows []json.RawMessage, next string, err error) {
	q := url.Values{}
	if o.Limit > 0 {
		q.Set("limit", fmt.Sprint(o.Limit))
	}
	if o.Before != "" {
		q.Set("before", o.Before)
	} else if o.Offset > 0 {
		q.Set("offset", fmt.Sprint(o.Offset))
	}
	if !o.From.IsZero() {
		q.Set("from", o.From.UTC().Format(time.RFC3339Nano))
	}
	if !o.To.IsZero() {
		q.Set("to", o.To.UTC().Format(time.RFC3339Nano))
	}
	resp, err := c.get(ctx, "/api/v1/telemetry/"+deviceID, q)
	if err != nil {
		return nil, "", err
	}
	if err := json.Unmarshal(resp.Body, &rows); err != nil {
		return nil, "", fmt.Errorf("the reply is not a list: %w", err)
	}
	return rows, resp.Header.Get("X-Next-Before"), nil
}

// ExportMaxSpan is the longest window the export route accepts.
const ExportMaxSpan = 31 * 24 * time.Hour

// Export streams a machine's readings as CSV, oldest first. The caller closes the body.
func (c *Client) Export(ctx context.Context, deviceID string, from, to time.Time) (io.ReadCloser, error) {
	q := url.Values{}
	q.Set("device_id", deviceID)
	q.Set("from_ts", from.UTC().Format(time.RFC3339Nano))
	if !to.IsZero() {
		q.Set("to_ts", to.UTC().Format(time.RFC3339Nano))
	}
	body, _, err := c.Stream(ctx, Request{Method: http.MethodGet, Path: "/api/v1/telemetry/export", Query: q})
	return body, err
}
