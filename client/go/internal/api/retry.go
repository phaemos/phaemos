package api

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// Clock lets the waits between retries be replaced in tests.
type Clock interface {
	Now() time.Time
	Sleep(ctx context.Context, d time.Duration) error
}

type realClock struct{}

func (realClock) Now() time.Time { return time.Now() }

func (realClock) Sleep(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// RetryPolicy says what is tried again.
//
//   - A request that only reads (GET) or one the caller marks Idempotent, is retried after a network
//     failure and after 502, 503 and 504, up to MaxAttempts tries in all, waiting BaseDelay then double
//     that and so on up to MaxDelay.
//   - 429 is retried for any request, because the limiter answers before the request is handled so
//     nothing was done. The wait is the Retry-After the server named (DefaultRetryAfter when it named
//     none) and a wait longer than MaxRetryAfter is not waited out: the 429 is returned. At most
//     Max429 waits are made.
//   - A write that is not marked Idempotent is never retried after a network failure or a 5xx, because
//     the server may have done it.
//   - A certificate failure is never retried.
type RetryPolicy struct {
	MaxAttempts       int
	BaseDelay         time.Duration
	MaxDelay          time.Duration
	MaxRetryAfter     time.Duration
	DefaultRetryAfter time.Duration
	Max429            int
}

// DefaultRetry is what the command line tool uses.
var DefaultRetry = RetryPolicy{
	MaxAttempts:       4,
	BaseDelay:         500 * time.Millisecond,
	MaxDelay:          8 * time.Second,
	MaxRetryAfter:     60 * time.Second,
	DefaultRetryAfter: 10 * time.Second,
	Max429:            3,
}

// NoRetry never retries.
var NoRetry = RetryPolicy{}

// ParseRetryAfter reads the whole-seconds form of Retry-After. The date form needs the clocks to agree
// and is treated as absent.
func ParseRetryAfter(value string) (time.Duration, bool) {
	secs, err := strconv.ParseUint(strings.TrimSpace(value), 10, 32)
	if err != nil {
		return 0, false
	}
	return time.Duration(secs) * time.Second, true
}

func isCertificateError(err error) bool {
	var unknown x509.UnknownAuthorityError
	var invalid x509.CertificateInvalidError
	var host x509.HostnameError
	var verify *tls.CertificateVerificationError
	return errors.As(err, &unknown) || errors.As(err, &invalid) || errors.As(err, &host) || errors.As(err, &verify)
}

// decide returns whether to try again and how long to wait first.
func (p RetryPolicy) decide(r Request, status int, retryAfter string, netErr error, attempt, waits429 int) (bool, time.Duration, bool) {
	canRepeat := r.Method == http.MethodGet || r.Idempotent
	backoff := p.BaseDelay << min(attempt, 20)
	if backoff > p.MaxDelay || backoff <= 0 {
		backoff = p.MaxDelay
	}
	switch {
	case r.NoRetry:
		return false, 0, false
	case netErr != nil:
		if !canRepeat || isCertificateError(netErr) || errors.Is(netErr, context.Canceled) || errors.Is(netErr, context.DeadlineExceeded) {
			return false, 0, false
		}
		return attempt+1 < p.MaxAttempts, backoff, false
	case status == http.StatusTooManyRequests:
		if waits429 >= p.Max429 {
			return false, 0, false
		}
		wait, ok := ParseRetryAfter(retryAfter)
		if !ok {
			wait = p.DefaultRetryAfter
		}
		if wait > p.MaxRetryAfter {
			return false, 0, false
		}
		return true, wait, true
	case status == http.StatusBadGateway || status == http.StatusServiceUnavailable || status == http.StatusGatewayTimeout:
		if !canRepeat || attempt+1 >= p.MaxAttempts {
			return false, 0, false
		}
		if wait, ok := ParseRetryAfter(retryAfter); ok && wait > backoff && wait <= p.MaxRetryAfter {
			backoff = wait
		}
		return true, backoff, false
	}
	return false, 0, false
}

// SystemClock is the real clock.
func SystemClock() Clock { return realClock{} }
