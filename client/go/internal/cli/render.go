package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/phaemos/client/go/internal/api"
)

type outputFormat string

const (
	formatTable outputFormat = "table"
	formatJSON  outputFormat = "json"
	formatJSONL outputFormat = "jsonl"
)

func parseFormat(text string) (outputFormat, error) {
	switch outputFormat(text) {
	case formatTable, formatJSON, formatJSONL:
		return outputFormat(text), nil
	case "":
		return formatTable, nil
	}
	return "", usageErr("--output must be table, json or jsonl (not %q)", text)
}

// cell is one table cell. Style is a colour name used only on a terminal.
type cell struct {
	Text  string
	Style string
}

func plain(text string) cell { return cell{Text: text} }

type table struct {
	Headers []string
	Rows    [][]cell
}

func (t *table) add(cells ...cell) { t.Rows = append(t.Rows, cells) }

// painter decides about colour once per run.
type painter struct{ on bool }

var ansi = map[string]string{"green": "32", "red": "31", "yellow": "33", "dim": "2", "bold": "1"}

func (p painter) paint(c cell, width int) string {
	pad := width - utf8.RuneCountInString(c.Text)
	if pad < 0 {
		pad = 0
	}
	text := c.Text
	if p.on && c.Style != "" {
		if code, ok := ansi[c.Style]; ok {
			text = "\x1b[" + code + "m" + text + "\x1b[0m"
		}
	}
	return text + strings.Repeat(" ", pad)
}

// renderTable writes aligned columns on a terminal and tab-separated rows otherwise. There is no
// drawing in either and no colour off a terminal.
func renderTable(w io.Writer, t *table, tty bool, p painter) {
	if !tty {
		fmt.Fprintln(w, strings.Join(t.Headers, "\t"))
		for _, row := range t.Rows {
			parts := make([]string, len(row))
			for i, c := range row {
				parts[i] = strings.ReplaceAll(c.Text, "\t", " ")
			}
			fmt.Fprintln(w, strings.Join(parts, "\t"))
		}
		return
	}
	widths := make([]int, len(t.Headers))
	for i, h := range t.Headers {
		widths[i] = utf8.RuneCountInString(h)
	}
	for _, row := range t.Rows {
		for i, c := range row {
			if n := utf8.RuneCountInString(c.Text); i < len(widths) && n > widths[i] {
				widths[i] = n
			}
		}
	}
	line := func(cells []cell) {
		var b strings.Builder
		for i, c := range cells {
			if i > 0 {
				b.WriteString("  ")
			}
			if i == len(cells)-1 {
				// no trailing spaces on the last column
				b.WriteString(strings.TrimRight(p.paint(c, widths[i]), " "))
			} else {
				b.WriteString(p.paint(c, widths[i]))
			}
		}
		fmt.Fprintln(w, strings.TrimRight(b.String(), " "))
	}
	head := make([]cell, len(t.Headers))
	for i, h := range t.Headers {
		head[i] = cell{Text: h, Style: "bold"}
	}
	line(head)
	for _, row := range t.Rows {
		line(row)
	}
}

// kv is a list of name and value pairs for one object.
type kv struct{ rows [][2]cell }

func (k *kv) add(name, value string) { k.rows = append(k.rows, [2]cell{plain(name), plain(value)}) }
func (k *kv) addStyled(name, value, style string) {
	k.rows = append(k.rows, [2]cell{plain(name), {Text: value, Style: style}})
}

func renderKV(w io.Writer, k *kv, tty bool, p painter) {
	if !tty {
		for _, r := range k.rows {
			fmt.Fprintf(w, "%s\t%s\n", r[0].Text, strings.ReplaceAll(r[1].Text, "\n", " "))
		}
		return
	}
	width := 0
	for _, r := range k.rows {
		if n := utf8.RuneCountInString(r[0].Text); n > width {
			width = n
		}
	}
	for _, r := range k.rows {
		fmt.Fprintf(w, "%s  %s\n", p.paint(cell{Text: r[0].Text, Style: "dim"}, width), strings.TrimRight(p.paint(r[1], 0), " "))
	}
}

// compactJSON writes one JSON document on one line.
func compactJSON(w io.Writer, raw []byte) error {
	var buf bytes.Buffer
	if err := json.Compact(&buf, raw); err != nil {
		return fmt.Errorf("the server's reply is not JSON: %w", err)
	}
	buf.WriteByte('\n')
	_, err := w.Write(buf.Bytes())
	return err
}

// writeList writes items as one JSON array or as one line each.
func writeList(w io.Writer, items []json.RawMessage, format outputFormat) error {
	if format == formatJSONL {
		for _, item := range items {
			if err := compactJSON(w, item); err != nil {
				return err
			}
		}
		return nil
	}
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, item := range items {
		if i > 0 {
			buf.WriteByte(',')
		}
		var one bytes.Buffer
		if err := json.Compact(&one, item); err != nil {
			return err
		}
		buf.Write(one.Bytes())
	}
	buf.WriteString("]\n")
	_, err := w.Write(buf.Bytes())
	return err
}

// timeFmt formats a time for a person: local, with the zone.
func timeFmt(t api.Time, loc *time.Location) string {
	if t.IsZero() {
		return "-"
	}
	return t.In(loc).Format("2006-01-02 15:04:05 MST")
}

func isoUTC(t time.Time) string { return t.UTC().Format(time.RFC3339) }

func str(p *string) string {
	if p == nil || *p == "" {
		return "-"
	}
	return *p
}

func clip(text string, n int) string {
	text = oneLine(text)
	if utf8.RuneCountInString(text) <= n {
		return text
	}
	r := []rune(text)
	return string(r[:n-1]) + "…"
}

func ago(seconds *int64) string {
	if seconds == nil {
		return "never"
	}
	d := time.Duration(*seconds) * time.Second
	switch {
	case d < time.Minute:
		return fmt.Sprintf("%ds ago", int(d.Seconds()))
	case d < time.Hour:
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	case d < 48*time.Hour:
		return fmt.Sprintf("%dh ago", int(d.Hours()))
	}
	return fmt.Sprintf("%dd ago", int(d.Hours()/24))
}
