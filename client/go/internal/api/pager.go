package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
)

// PageStyle names the paging parameters of a list route. The API is moving to one contract: limit and
// offset on every list, with X-Total-Count. Until every route has moved, devices and tickets still page
// with skip, so a request carries both names: a route ignores the one it does not know.
type PageStyle struct {
	// MaxPage is the most the route allows in one page.
	MaxPage int
}

// Style is the one paging contract.
var Style = PageStyle{MaxPage: 200}

// DefaultListLimit is how many items a list returns unless the caller asks for another number.
const DefaultListLimit = 1000

// MaxListLimit is the largest number a caller may ask for. It keeps one command from walking a whole
// history.
const MaxListLimit = 100000

// ListResult is everything a pager collected.
type ListResult struct {
	Items []json.RawMessage
	// Total is the server's X-Total-Count for the same filters or -1 when the route sends none.
	Total int
	// More is true when the server has more than were returned.
	More bool
	// keyset says the walk used the server's X-Next-Before cursor.
	keyset bool
}

// List pages through a list route until limit items are collected or the list ends. The items are kept
// as the server wrote them. A page that carries X-Next-Before is walked by keyset (that cursor is sent back as
// `before`), which reads straight off an index however far back. Without it the walk uses offset.
func (c *Client) List(ctx context.Context, path string, query url.Values, style PageStyle, limit int) (*ListResult, error) {
	if limit <= 0 {
		limit = DefaultListLimit
	}
	if limit > MaxListLimit {
		return nil, fmt.Errorf("a list may hold at most %d items", MaxListLimit)
	}
	result := &ListResult{Total: -1}
	cursor := ""
	keyset := false
	for len(result.Items) < limit {
		want := min(limit-len(result.Items), style.MaxPage)
		q := url.Values{}
		for k, v := range query {
			q[k] = v
		}
		q.Set("limit", strconv.Itoa(want))
		if keyset {
			q.Set("before", cursor)
		} else {
			q.Set("offset", strconv.Itoa(len(result.Items)))
			q.Set("skip", strconv.Itoa(len(result.Items)))
		}
		resp, err := c.Do(ctx, Request{Method: "GET", Path: path, Query: q})
		if err != nil {
			return nil, err
		}
		if total, err := strconv.Atoi(resp.Header.Get("X-Total-Count")); err == nil {
			result.Total = total
		}
		var page []json.RawMessage
		if err := json.Unmarshal(resp.Body, &page); err != nil {
			return nil, fmt.Errorf("%s: the reply is not a list: %w", path, err)
		}
		if len(page) > 0 && len(result.Items) > 0 && string(page[0]) == string(result.Items[0]) {
			// the same first item again: the route ignored the paging parameters
			return nil, fmt.Errorf("%s: the route ignored its paging parameters (it sent the same page twice)", path)
		}
		result.Items = append(result.Items, page...)
		if len(page) > want {
			// a route that ignores limit sent everything at once
			break
		}
		if len(page) < want {
			break
		}
		if next := resp.Header.Get("X-Next-Before"); next != "" {
			keyset, cursor = true, next
			result.keyset = true
			continue
		}
		if result.Total >= 0 && len(result.Items) >= result.Total {
			break
		}
	}
	switch {
	case result.Total >= 0 && !result.keyset:
		result.More = result.Total > len(result.Items)
	case result.Total >= 0:
		result.More = result.Total > len(result.Items) && len(result.Items) >= limit
	default:
		// no total: a full last page at the limit may have more behind it
		result.More = len(result.Items) >= limit
	}
	return result, nil
}

// DecodeAll turns raw items into typed values.
func DecodeAll[T any](items []json.RawMessage) ([]T, error) {
	out := make([]T, 0, len(items))
	for _, raw := range items {
		var v T
		if err := json.Unmarshal(raw, &v); err != nil {
			return nil, fmt.Errorf("an item could not be read: %w", err)
		}
		out = append(out, v)
	}
	return out, nil
}
