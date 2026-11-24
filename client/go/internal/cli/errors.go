package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/phaemos/client/go/internal/api"
)

// Exit codes. Scripts can rely on these.
const (
	ExitOK          = 0
	ExitFailure     = 1
	ExitUsage       = 2
	ExitNotSignedIn = 3
	ExitForbidden   = 4
	ExitNotFound    = 5
	ExitConflict    = 6
	ExitRateLimited = 7
	ExitUnavailable = 8
)

// exitError is what a command returns when it fails. Kind is the stable word a script reads from the
// JSON form of an error.
type exitError struct {
	Code    int
	Kind    string
	Status  int
	Message string
	// APICode is the API's own stable error code, when the reply had one.
	APICode string
	// silent means the message was already shown as part of the result, so it is not printed again.
	silent bool
}

func (e *exitError) Error() string { return e.Message }

var kinds = map[int]string{
	ExitFailure:     "general",
	ExitUsage:       "usage",
	ExitNotSignedIn: "unauthenticated",
	ExitForbidden:   "forbidden",
	ExitNotFound:    "not_found",
	ExitConflict:    "conflict",
	ExitRateLimited: "rate_limited",
	ExitUnavailable: "unavailable",
}

func newExit(code int, format string, args ...any) *exitError {
	return &exitError{Code: code, Kind: kinds[code], Message: fmt.Sprintf(format, args...)}
}

func usageErr(format string, args ...any) *exitError { return newExit(ExitUsage, format, args...) }

// classify turns any error into an exitError.
func classify(err error) *exitError {
	var ee *exitError
	if errors.As(err, &ee) {
		return ee
	}
	var apiErr *api.Error
	if errors.As(err, &apiErr) {
		return fromAPI(apiErr)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return newExit(ExitUnavailable, "timed out: raise --timeout or check the network")
	}
	var nomachine *api.ErrNoMachine
	if errors.As(err, &nomachine) {
		return newExit(ExitNotFound, "%s", nomachine.Error())
	}
	var ambiguous *api.ErrAmbiguous
	if errors.As(err, &ambiguous) {
		return newExit(ExitConflict, "%s", ambiguous.Error())
	}
	return newExit(ExitFailure, "%s", oneLine(err.Error()))
}

func oneLine(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

func fromAPI(e *api.Error) *exitError {
	msg := oneLine(e.Message)
	if e.Err != nil && msg == "" {
		msg = oneLine(e.Err.Error())
	}
	out := &exitError{Status: e.Status, APICode: e.Code}
	// the API's stable code is read before the status and never a sentence
	switch e.Code {
	case "idempotency_in_progress":
		out.Code = ExitConflict
		out.Kind = kinds[out.Code]
		out.Message = "the first request with this key is still being handled: wait a moment, then run the command again"
		return out
	case "idempotency_key_reused":
		out.Code = ExitConflict
		out.Kind = kinds[out.Code]
		out.Message = "this idempotency key was already used for a different request: run the command again to make a new key"
		return out
	}
	switch {
	case e.Status == 401:
		out.Code = ExitNotSignedIn
		out.Message = "the token was refused (it may have expired or been revoked). Sign in again with: phaemosctl auth login"
		if msg != "" {
			out.Message = fmt.Sprintf("the token was refused: %s. Sign in again with: phaemosctl auth login", msg)
		}
	case e.Status == 403:
		out.Code = ExitForbidden
		out.Message = "not allowed: " + msg
	case e.Status == 404:
		out.Code = ExitNotFound
		out.Message = "not found: " + msg
	case e.Status == 400 || e.Status == 409 || e.Status == 422:
		out.Code = ExitConflict
		out.Message = "the server refused the request: " + msg
	case e.Status == 429:
		out.Code = ExitRateLimited
		out.Message = "rate limited: " + msg
		if e.RetryAfter > 0 {
			out.Message += fmt.Sprintf(" (the server asked for %d s)", int(e.RetryAfter.Seconds()))
		}
		out.Message += ". Try again later or lower the rate"
	case e.Status >= 500 || e.Status == 408:
		out.Code = ExitUnavailable
		out.Message = fmt.Sprintf("the server failed (%d): %s", e.Status, msg)
	case e.Status == 0:
		out.Code = ExitUnavailable
		out.Message = "cannot reach the server: " + msg
	default:
		out.Code = ExitFailure
		out.Message = fmt.Sprintf("unexpected answer (%d): %s", e.Status, msg)
	}
	out.Message = strings.TrimSpace(strings.ReplaceAll(out.Message, ": . ", ". "))
	out.Kind = kinds[out.Code]
	return out
}

// jsonError is the form an error takes with --output json.
func (e *exitError) json() []byte {
	body := map[string]any{"code": e.Kind, "exit": e.Code, "message": e.Message}
	if e.Status != 0 {
		body["status"] = e.Status
	}
	if e.APICode != "" {
		body["api_code"] = e.APICode
	}
	out, _ := json.Marshal(body)
	return out
}
