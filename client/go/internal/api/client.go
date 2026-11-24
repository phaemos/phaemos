// Package api is a small client for the PHAEMOS HTTP API.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"
)

// tokenShape matches anything that looks like an API token, so one that a server echoes is blanked
// even when it is not the token this client holds.
var tokenShape = regexp.MustCompile(`pht_[A-Za-z0-9_\-]+`)

// maxReplyBytes caps how much of a reply is read, so a hostile or broken server cannot use up memory.
const maxReplyBytes = 1 << 20

// maxErrorText caps the server text echoed in an error, so a long or odd reply cannot flood a terminal or a log.
const maxErrorText = 200

// ErrCounterRefused is returned (wrapped) when the API answers 409: the post's boot and seq are not
// newer than the last accepted for this key. If the state folder was wiped an admin can accept a
// new counter for the machine.
var ErrCounterRefused = errors.New("the API refused this post's boot and seq as older than the last it accepted (409): if the state folder was wiped an admin can accept a new counter")

// Client talks to one PHAEMOS server. APIKey is a device key, used for telemetry ingest. Token is an
// API token (pht_...) for everything else. When Counter is set, readings are stamped with boot,
// seq and up.
type Client struct {
	BaseURL string
	APIKey  string
	Token   string
	HTTP    *http.Client
	Counter *Counter
	// Retry is the retry policy. New leaves it at NoRetry so the device calls behave as they always
	// did. The command line tool sets DefaultRetry.
	Retry RetryPolicy
	// Clock makes the waits between retries testable. Nil means the real clock.
	Clock Clock
	// MaxReply caps how much of a reply is read. Zero means maxReplyBytes.
	MaxReply int64
	// UserAgent is sent with every request when set.
	UserAgent string
	// Trace, when set, is called after each attempt with the method, the path (no query) and the status
	// (0 when no reply came) and how long it took. It never sees a header or a body.
	Trace func(method, path string, status int, took time.Duration)
	// OnDeprecated, when set, is called when an answer carries Deprecation or Sunset headers. It gets the
	// method, the path and the Sunset date (empty when none).
	OnDeprecated func(method, path, sunset string)
}

// IsDuplicate reports whether a reply says the API already has this exact post (answered 200 with
// status "duplicate" and nothing stored). The post was delivered earlier.
func IsDuplicate(reply map[string]any) bool {
	return reply["status"] == "duplicate" && reply["stored"] == false
}

// New returns a client with a time-out. It never follows a redirect, so the device key is not sent
// to another address. It uses Go's default TLS settings, which verify the server's certificate.
func New(baseURL, apiKey string) *Client {
	return &Client{
		BaseURL: NormaliseURL(baseURL),
		APIKey:  apiKey,
		Clock:   realClock{},
		HTTP: &http.Client{
			Timeout: 10 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

// NormaliseURL strips trailing slashes from a base address, so no request carries a double or trailing slash.
func NormaliseURL(raw string) string { return strings.TrimRight(strings.TrimSpace(raw), "/") }

// CheckURL returns an error unless the address is https:// or a loopback http:// address. Plain
// http:// to any other host is refused unless allowInsecure is set, because it sends the key or token
// and the readings across the network unencrypted.
func CheckURL(raw string, allowInsecure bool) error {
	u, err := url.Parse(NormaliseURL(raw))
	if err != nil || u.Hostname() == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return fmt.Errorf("the API address must be an http:// or https:// address with a host")
	}
	if u.User != nil {
		return fmt.Errorf("the API address must not hold a user name or password")
	}
	// the server answers 404 for a path with a trailing slash and never redirects it, so the address is the
	// base only and the tool adds each route itself
	if p := u.Path; p != "" || u.RawQuery != "" {
		return fmt.Errorf("the API address must be the base address only, for example https://api.example.org: remove the path %q (the tool adds each route itself)", p)
	}
	if u.Scheme == "http" && !IsLocalHost(u.Hostname()) && !allowInsecure {
		return fmt.Errorf("the API address is plain http:// to a host that is not local, which sends the key or token and the readings unencrypted: use https:// or pass --allow-insecure-http for bench testing only")
	}
	return nil
}

// IsLocalHost reports whether host is localhost or a loopback address.
func IsLocalHost(host string) bool {
	// only the name localhost and literal loopback addresses. Another name that ends in .localhost
	// is not resolved here, so it is not known to be local.
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// errorText turns a server's reply into text that is safe to show: printable characters only, no
// longer than maxErrorText and with each secret blanked in case the server echoes it.
func errorText(data []byte, secrets ...string) string {
	text := tokenShape.ReplaceAllString(strings.TrimSpace(string(data)), "<token>")
	for _, secret := range secrets {
		if secret != "" {
			text = strings.ReplaceAll(text, secret, "<secret>")
		}
	}
	text = strings.Map(func(r rune) rune {
		if unicode.IsPrint(r) {
			return r
		}
		return ' '
	}, text)
	runes := []rune(text)
	if len(runes) > maxErrorText {
		return string(runes[:maxErrorText]) + "... (cut)"
	}
	return text
}

// Status calls the public status endpoint.
func (c *Client) Status(ctx context.Context) (map[string]any, error) {
	resp, err := c.Do(ctx, Request{Method: http.MethodGet, Path: "/status"})
	if err != nil {
		return nil, err
	}
	return decodeObject(resp.Body)
}

// SendReading posts one telemetry reading and returns the stored row with its anomaly score. It is
// never retried: a device post behaves exactly as it always has.
func (c *Client) SendReading(ctx context.Context, reading map[string]any) (map[string]any, error) {
	if c.Counter != nil {
		stamped, err := c.Counter.Stamp(reading)
		if err != nil {
			return nil, err
		}
		reading = stamped
	}
	resp, err := c.Do(ctx, Request{Method: http.MethodPost, Path: "/api/v1/telemetry", Body: reading, UseKey: true, NoRetry: true})
	var apiErr *Error
	if errors.As(err, &apiErr) && apiErr.Status == http.StatusConflict {
		apiErr.Err = ErrCounterRefused
		apiErr.Message = ""
	}
	if err != nil {
		return nil, err
	}
	return decodeObject(resp.Body)
}

func decodeObject(data []byte) (map[string]any, error) {
	out := map[string]any{}
	if len(data) > 0 {
		if err := json.Unmarshal(data, &out); err != nil {
			return nil, err
		}
	}
	return out, nil
}
