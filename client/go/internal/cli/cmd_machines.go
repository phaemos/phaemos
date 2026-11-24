package cli

import (
	"encoding/json"
	"flag"
	"fmt"
	"sort"
	"strings"

	"github.com/phaemos/client/go/internal/api"
)

func limitFlag(fs *flag.FlagSet) {
	fs.Int("limit", api.DefaultListLimit, fmt.Sprintf("most items to list (at most %d)", api.MaxListLimit))
}

func (r *runCtx) limit() (int, error) {
	n := r.integer("limit")
	if n < 1 || n > api.MaxListLimit {
		return 0, usageErr("--limit must be between 1 and %d", api.MaxListLimit)
	}
	return n, nil
}

func (r *runCtx) warnMore(res *api.ListResult, noun string) {
	if res.More {
		total := ""
		if res.Total >= 0 {
			total = fmt.Sprintf(" of %d", res.Total)
		}
		r.warn("showing %d%s %s: use --limit to see more", len(res.Items), total, noun)
	}
}

func init() {
	register(&command{
		path:    []string{"devices", "list"},
		summary: "list the machines you may read",
		desc: "Lists machines with their state, last seen time, link state, open alerts, model state and replay protection. " +
			"The list pages through everything up to --limit (default 1000). The open alert counts come from one extra read of " +
			"the open alerts (at most 1000), so a fleet with more open alerts than that shows counts that may be low.",
		examples: []string{
			"phaemosctl devices list",
			"phaemosctl devices list --status offline --output json",
			"phaemosctl devices list --tag pump-room --wide",
		},
		flags: func(fs *flag.FlagSet) {
			limitFlag(fs)
			fs.String("status", "", "only machines with this status (online or offline)")
			fs.String("tag", "", "only machines with this tag")
			fs.String("search", "", "only machines whose name contains this text")
			fs.Bool("wide", false, "also show the id, location, owner, tags and firmware")
		},
		needsToken: true,
		run:        runMachinesList,
	})
	register(&command{
		path:    []string{"devices", "show"},
		summary: "show one machine in full",
		desc: "Shows a machine by id or by name: its state, last seen time, link state, open alerts, anomaly model state, replay " +
			"protection and the latest vitals it reported. A name must match one machine exactly (ignoring case): the API has no " +
			"lookup by name, so the tool searches the list for it.",
		examples: []string{"phaemosctl devices show press-01", "phaemosctl devices show 6f1c0e5a-0000-0000-0000-000000000001 --output json"},
		args:     "<device>", minArgs: 1, maxArgs: 1, needsToken: true,
		run: runMachinesShow,
	})
}

func linkStyle(state string) string {
	switch state {
	case "online":
		return "green"
	case "late":
		return "yellow"
	case "offline":
		return "red"
	}
	return ""
}

func replayText(d api.Device) string {
	switch {
	case !d.ReplayProtected:
		return "off"
	case d.ReplayRefused > 0:
		return fmt.Sprintf("refused %d", d.ReplayRefused)
	}
	return "on"
}

func modelText(d api.Device) string {
	if d.Model == nil {
		return "-"
	}
	return d.Model.State
}

// openAlertCounts counts open alerts per machine, reading at most 1000.
func (r *runCtx) openAlertCounts() (map[string]int, bool) {
	res, err := r.client.ListAlerts(r.ctx, api.AlertFilter{OpenOnly: true}, api.DefaultListLimit)
	if err != nil {
		r.warn("could not read the open alerts, so the counts are left out: %s", classify(err).Message)
		return nil, false
	}
	alerts, err := api.DecodeAll[api.Alert](res.Items)
	if err != nil {
		return nil, false
	}
	counts := map[string]int{}
	for _, a := range alerts {
		if !a.Resolved {
			counts[a.DeviceID]++
		}
	}
	return counts, !res.More
}

func runMachinesList(r *runCtx) error {
	limit, err := r.limit()
	if err != nil {
		return err
	}
	res, err := r.client.ListDevices(r.ctx, r.str("search"), r.str("status"), r.str("tag"), limit)
	if err != nil {
		return err
	}
	r.warnMore(res, "machines")
	if r.format != formatTable {
		return writeList(r.out(), res.Items, r.format)
	}
	devices, err := api.DecodeAll[api.Device](res.Items)
	if err != nil {
		return err
	}
	counts, complete := r.openAlertCounts()
	wide := r.boolean("wide")
	t := &table{Headers: []string{"NAME", "STATE", "LINK", "LAST SEEN", "OPEN ALERTS", "MODEL", "REPLAY"}}
	if wide {
		t.Headers = append(t.Headers, "ID", "LOCATION", "OWNER", "TAGS", "FIRMWARE")
	}
	for _, d := range devices {
		alerts := "-"
		if counts != nil {
			alerts = fmt.Sprint(counts[d.ID])
			if !complete && counts[d.ID] > 0 {
				alerts += "+"
			}
		}
		row := []cell{
			plain(d.Name), {Text: d.Status, Style: linkStyle(d.Status)}, {Text: first(d.LinkState, "-"), Style: linkStyle(d.LinkState)},
			plain(timeFmt(d.LastSeen, r.loc())), plain(alerts), plain(modelText(d)), plain(replayText(d)),
		}
		if wide {
			row = append(row, plain(d.ID), plain(str(d.Location)), plain(str(d.OwnerName)), plain(first(strings.Join(d.Tags, ","), "-")), plain(str(d.FirmwareVersion)))
		}
		t.add(row...)
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

func runMachinesShow(r *runCtx) error {
	dev, raw, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var health map[string]any
	var holder struct {
		Health map[string]any `json:"health"`
	}
	if json.Unmarshal(raw, &holder) == nil {
		health = holder.Health
	}
	k := &kv{}
	k.add("name", dev.Name)
	k.add("id", dev.ID)
	k.addStyled("state", dev.Status, linkStyle(dev.Status))
	k.addStyled("link", first(dev.LinkState, "-"), linkStyle(dev.LinkState))
	k.add("last seen", timeFmt(dev.LastSeen, r.loc())+" ("+ago(dev.SecondsSinceLastPost)+")")
	k.add("expected interval", fmt.Sprintf("%d s", dev.ExpectedIntervalS))
	k.add("type", str(dev.Type))
	k.add("location", str(dev.Location))
	k.add("owner", str(dev.OwnerName))
	k.add("tags", first(strings.Join(dev.Tags, ", "), "-"))
	k.add("firmware", str(dev.FirmwareVersion))
	// open alerts for this machine
	if res, err := r.client.ListAlerts(r.ctx, api.AlertFilter{DeviceID: dev.ID, OpenOnly: true}, api.DefaultListLimit); err != nil {
		r.warn("could not read the alerts: %s", classify(err).Message)
		k.add("open alerts", "?")
	} else if alerts, err := api.DecodeAll[api.Alert](res.Items); err == nil {
		var open []api.Alert
		for _, a := range alerts {
			if !a.Resolved {
				open = append(open, a)
			}
		}
		text := fmt.Sprint(len(open))
		if res.More {
			text += "+ (only the newest " + fmt.Sprint(len(res.Items)) + " alerts were read)"
		}
		style := ""
		if len(open) > 0 {
			style = "red"
		}
		k.addStyled("open alerts", text, style)
		for i, a := range open {
			if i >= 5 {
				k.add("", fmt.Sprintf("... and %d more", len(open)-5))
				break
			}
			k.add("", fmt.Sprintf("%s  %s  %s", first(strPtr(a.Severity), "-"), clip(first(strPtr(a.Message), "-"), 70), a.ID))
		}
	}
	if m := dev.Model; m != nil {
		text := m.State
		if m.Scope != nil {
			text += " (" + *m.Scope + ")"
		}
		k.add("model", text)
		if m.HoursCollected != nil && m.HoursNeeded != nil {
			k.add("model data", fmt.Sprintf("%.1f of %.1f hours collected", *m.HoursCollected, *m.HoursNeeded))
		}
		if m.FalseAlertsPerWeek != nil {
			k.add("model false alerts", fmt.Sprintf("%.2f a week", *m.FalseAlertsPerWeek))
		}
		if !m.TrainedAt.IsZero() {
			k.add("model trained", timeFmt(m.TrainedAt, r.loc()))
		}
	}
	k.add("replay protection", replayText(dev))
	if dev.LastBoot != nil && dev.LastSeq != nil {
		k.add("replay counter", fmt.Sprintf("boot %d, seq %d", *dev.LastBoot, *dev.LastSeq))
	}
	if dev.ReplayStatus != nil {
		k.add("replay status", *dev.ReplayStatus)
	}
	if dev.ReplayWarning != nil {
		k.addStyled("replay warning", *dev.ReplayWarning, "yellow")
	}
	if len(health) > 0 {
		keys := make([]string, 0, len(health))
		for key := range health {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			v := health[key]
			if v == nil {
				continue
			}
			switch v.(type) {
			case map[string]any, []any:
				b, _ := json.Marshal(v)
				if string(b) == "{}" || string(b) == "[]" {
					continue
				}
				k.add("health "+key, clip(string(b), 120))
			default:
				k.add("health "+key, fmt.Sprint(v))
			}
		}
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

func strPtr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
