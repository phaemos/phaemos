package api

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// Error is the one error type for a request that failed. Status is the HTTP status or 0 when no
// reply came (a network failure or a time-out, in Err). Message is the server's own words, cleaned
// and cut. Neither the key nor the token is ever in it.
type Error struct {
	Method  string
	Path    string
	Status  int
	Message string
	// Code is the API's stable error code (a snake_case word) when the reply carried one. Scripts and the
	// tool read the code when it is there and the status when it is not and never match on a sentence.
	Code       string
	RetryAfter time.Duration
	Err        error
}

func (e *Error) Error() string {
	where := e.Method + " " + e.Path
	switch {
	case e.Err != nil && e.Status == 0:
		return fmt.Sprintf("%s: %v", where, e.Err)
	case e.Err != nil:
		return fmt.Sprintf("%s: %d %v", where, e.Status, e.Err)
	case e.Message != "":
		return fmt.Sprintf("%s: %d %s", where, e.Status, e.Message)
	default:
		return fmt.Sprintf("%s: %d", where, e.Status)
	}
}

func (e *Error) Unwrap() error { return e.Err }

// parseErrorBody pulls the readable part and the stable code out of an API error body. The API
// answers {"code": "...", "detail": "a sentence", "request_id": "...", "errors": [{"loc", "msg", "type"}]}.
// Older answers have only {"detail": "..."} or, for a refused field, a detail that is a list. Anything
// else is shown as text.
func parseErrorBody(data []byte) (message, code string) {
	var body struct {
		Code   string          `json:"code"`
		Detail json.RawMessage `json:"detail"`
		Errors []fieldError    `json:"errors"`
	}
	if json.Unmarshal(data, &body) != nil {
		return string(data), ""
	}
	var text string
	if len(body.Detail) > 0 && json.Unmarshal(body.Detail, &text) == nil {
		message = text
	} else if len(body.Detail) > 0 {
		var list []fieldError
		if json.Unmarshal(body.Detail, &list) == nil && len(list) > 0 {
			body.Errors = list
		} else {
			message = string(data)
		}
	}
	if len(body.Errors) > 0 {
		parts := make([]string, 0, len(body.Errors))
		for _, item := range body.Errors {
			parts = append(parts, item.String())
		}
		if message == "" {
			message = strings.Join(parts, "; ")
		} else {
			message += ": " + strings.Join(parts, "; ")
		}
	}
	if message == "" && body.Code == "" && len(body.Detail) == 0 {
		message = string(data)
	}
	return message, body.Code
}

type fieldError struct {
	Loc []any  `json:"loc"`
	Msg string `json:"msg"`
}

func (f fieldError) String() string {
	where := make([]string, 0, len(f.Loc))
	for _, l := range f.Loc {
		where = append(where, fmt.Sprint(l))
	}
	if len(where) > 0 {
		return strings.Join(where, ".") + ": " + f.Msg
	}
	return f.Msg
}
