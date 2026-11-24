package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Request describes one call.
type Request struct {
	Method string
	Path   string
	Query  url.Values
	Body   any
	// Idempotent marks a write that is safe to repeat after a network failure or a 5xx.
	Idempotent bool
	// UseKey sends the device key in X-API-Key. Without it the API token is sent as a bearer token
	// when there is one. Both are never sent together.
	UseKey bool
	// NoRetry turns every retry off for this call.
	NoRetry bool
	// Headers are extra request headers, for example Idempotency-Key. They never hold a credential.
	Headers map[string]string
}

// Response is a reply with a status under 300.
type Response struct {
	Status int
	Header http.Header
	Body   []byte
}

func (c *Client) clock() Clock {
	if c.Clock == nil {
		return realClock{}
	}
	return c.Clock
}

func (c *Client) secrets() []string { return []string{c.APIKey, c.Token} }

func (c *Client) scrub(text string) string {
	text = tokenShape.ReplaceAllString(text, "<token>")
	for _, secret := range c.secrets() {
		if secret != "" {
			text = strings.ReplaceAll(text, secret, "<secret>")
		}
	}
	return text
}

func (c *Client) build(ctx context.Context, r Request) (*http.Request, error) {
	var payload io.Reader
	if r.Body != nil {
		raw, err := json.Marshal(r.Body)
		if err != nil {
			return nil, err
		}
		payload = bytes.NewReader(raw)
	}
	target := c.BaseURL + r.Path
	if len(r.Query) > 0 {
		target += "?" + r.Query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, r.Method, target, payload)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	for k, v := range r.Headers {
		req.Header.Set(k, v)
	}
	switch {
	case r.UseKey && c.APIKey != "":
		req.Header.Set("X-API-Key", c.APIKey)
	case !r.UseKey && c.Token != "":
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	return req, nil
}

// noteDeprecation tells the caller when an answer says its route is going away (Deprecation and Sunset
// headers), so someone running an old tool learns it before the route is removed.
func (c *Client) noteDeprecation(r Request, h http.Header) {
	if c.OnDeprecated == nil || h == nil {
		return
	}
	dep, sunset := h.Get("Deprecation"), h.Get("Sunset")
	if dep != "" || sunset != "" {
		c.OnDeprecated(r.Method, r.Path, sunset)
	}
}

func (c *Client) trace(r Request, status int, began time.Time) {
	if c.Trace != nil {
		c.Trace(r.Method, r.Path, status, time.Since(began))
	}
}

func (c *Client) netError(r Request, err error) *Error {
	// the standard library's error holds the address, never a header, but the secrets are blanked anyway
	return &Error{Method: r.Method, Path: r.Path, Err: errors.New(c.scrub(err.Error()))}
}

func (c *Client) statusError(r Request, res *http.Response, data []byte) *Error {
	message, code := parseErrorBody(data)
	e := &Error{Method: r.Method, Path: r.Path, Status: res.StatusCode, Message: errorText([]byte(message), c.secrets()...), Code: errorText([]byte(code), c.secrets()...)}
	if wait, ok := ParseRetryAfter(res.Header.Get("Retry-After")); ok {
		e.RetryAfter = wait
	}
	return e
}

// Do sends the request, applying the retry policy and returns the reply when its status is under 300.
// Any other outcome is an *Error.
func (c *Client) Do(ctx context.Context, r Request) (*Response, error) {
	max := c.MaxReply
	if max <= 0 {
		max = maxReplyBytes
	}
	attempt, waits := 0, 0
	for {
		began := time.Now()
		req, err := c.build(ctx, r)
		if err != nil {
			return nil, &Error{Method: r.Method, Path: r.Path, Err: errors.New(c.scrub(err.Error()))}
		}
		res, err := c.HTTP.Do(req)
		var apiErr *Error
		var out *Response
		var retryAfter string
		status := 0
		if err != nil {
			apiErr = c.netError(r, err)
		} else {
			status = res.StatusCode
			retryAfter = res.Header.Get("Retry-After")
			c.noteDeprecation(r, res.Header)
			data, readErr := io.ReadAll(io.LimitReader(res.Body, max+1))
			_ = res.Body.Close()
			switch {
			case readErr != nil:
				err = readErr
				apiErr = c.netError(r, readErr)
			case int64(len(data)) > max && status < 300:
				return nil, &Error{Method: r.Method, Path: r.Path, Status: status, Err: fmt.Errorf("the reply is longer than %d bytes", max)}
			case status >= 300:
				// an error body is cut at the cap and shown cut: the status is what matters
				if int64(len(data)) > max {
					data = data[:max]
				}
				apiErr = c.statusError(r, res, data)
			default:
				out = &Response{Status: status, Header: res.Header, Body: data}
			}
		}
		c.trace(r, status, began)
		if apiErr == nil {
			return out, nil
		}
		again, wait, is429 := c.Retry.decide(r, status, retryAfter, err, attempt, waits)
		if !again {
			return nil, apiErr
		}
		if is429 {
			waits++
		} else {
			attempt++
		}
		if sleepErr := c.clock().Sleep(ctx, wait); sleepErr != nil {
			return nil, &Error{Method: r.Method, Path: r.Path, Err: sleepErr}
		}
	}
}

// Stream sends the request and returns the open reply body once the status is under 300. The caller
// closes it. There is no size cap and no per-request time-out: the context bounds the whole call. The
// retry policy applies until the reply starts and never after.
func (c *Client) Stream(ctx context.Context, r Request) (io.ReadCloser, http.Header, error) {
	streaming := *c.HTTP
	streaming.Timeout = 0
	attempt, waits := 0, 0
	for {
		began := time.Now()
		req, err := c.build(ctx, r)
		if err != nil {
			return nil, nil, &Error{Method: r.Method, Path: r.Path, Err: errors.New(c.scrub(err.Error()))}
		}
		res, err := streaming.Do(req)
		status := 0
		var apiErr *Error
		retryAfter := ""
		if err != nil {
			apiErr = c.netError(r, err)
		} else {
			status = res.StatusCode
			retryAfter = res.Header.Get("Retry-After")
			if status < 300 {
				c.trace(r, status, began)
				return res.Body, res.Header, nil
			}
			data, _ := io.ReadAll(io.LimitReader(res.Body, 64<<10))
			_ = res.Body.Close()
			apiErr = c.statusError(r, res, data)
		}
		c.trace(r, status, began)
		again, wait, is429 := c.Retry.decide(r, status, retryAfter, err, attempt, waits)
		if !again {
			return nil, nil, apiErr
		}
		if is429 {
			waits++
		} else {
			attempt++
		}
		if sleepErr := c.clock().Sleep(ctx, wait); sleepErr != nil {
			return nil, nil, &Error{Method: r.Method, Path: r.Path, Err: sleepErr}
		}
	}
}
