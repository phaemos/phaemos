package cli

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"strings"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:    []string{"alerts", "list"},
		summary: "list alerts, newest first",
		desc: "Lists alerts you may read. --open shows only those still open. --device limits the list to one device (by id or name). " +
			"--severity, --kind and --category are the server's own filters.",
		examples: []string{
			"phaemosctl alerts list --open",
			"phaemosctl alerts list --open --severity critical --output json",
			"phaemosctl alerts list --device press-01 --limit 50",
		},
		flags: func(fs *flag.FlagSet) {
			limitFlag(fs)
			fs.Bool("open", false, "only alerts that are still open")
			fs.String("severity", "", "only this severity: info, warning or critical")
			fs.String("kind", "", "only this kind: rule, anomaly, offline, reset_loop, unscored, sensor, clipping or board_mismatch")
			fs.String("category", "", "only machine or monitoring alerts")
			fs.String("device", "", "only this device (id or name)")
			fs.String("machine", "", "same as --device")
			fs.Bool("wide", false, "do not cut long messages")
		},
		needsToken: true,
		run:        runAlertsList,
	})
	register(&command{
		path:     []string{"alerts", "show"},
		summary:  "show one alert in full",
		desc:     "Shows an alert by id: its device, severity, state, message, the times it was first and last seen and the figures behind it.",
		examples: []string{"phaemosctl alerts show 0b6c1f0e-1111-4222-8333-444455556666", "phaemosctl alerts show 0b6c1f0e-1111-4222-8333-444455556666 --output json"},
		args:     "<id>", minArgs: 1, maxArgs: 1, needsToken: true,
		run: runAlertsShow,
	})
	register(&command{
		path:    []string{"alerts", "resolve"},
		summary: "mark an alert resolved",
		desc: "Resolves an alert by id after asking you to confirm. --yes skips the question. It never asks when standard input is not a " +
			"terminal: it stops with exit code 2 and says to pass --yes. The token needs the operate scope. The API has no separate acknowledge step, only resolve. A rule alert is only marked: " +
			"if its condition goes on, the server raises a new one. Resolving is safe to repeat, so a network failure is retried.",
		examples: []string{"phaemosctl alerts resolve 0b6c1f0e-1111-4222-8333-444455556666", "phaemosctl alerts resolve 0b6c1f0e-1111-4222-8333-444455556666 --yes"},
		args:     "<id>", minArgs: 1, maxArgs: 1, needsToken: true, scope: "operate",
		flags: func(fs *flag.FlagSet) { fs.Bool("yes", false, "do not ask for confirmation") },
		run:   runAlertsResolve,
	})
}

func (r *runCtx) machineID(ref string) (api.Device, error) {
	dev, _, err := r.client.ResolveDevice(r.ctx, ref)
	return dev, err
}

func (r *runCtx) deviceNames() map[string]string {
	res, err := r.client.ListDevices(r.ctx, "", "", "", api.DefaultListLimit)
	if err != nil {
		return nil
	}
	devices, err := api.DecodeAll[api.Device](res.Items)
	if err != nil {
		return nil
	}
	names := make(map[string]string, len(devices))
	for _, d := range devices {
		names[d.ID] = d.Name
	}
	return names
}

func sevStyle(sev string) string {
	switch strings.ToLower(sev) {
	case "critical":
		return "red"
	case "warning":
		return "yellow"
	}
	return ""
}

func runAlertsList(r *runCtx) error {
	limit, err := r.limit()
	if err != nil {
		return err
	}
	deviceID := ""
	if m := first(r.str("device"), r.str("machine")); m != "" {
		dev, err := r.machineID(m)
		if err != nil {
			return err
		}
		deviceID = dev.ID
	}
	severity, category, kind := strings.ToLower(r.str("severity")), r.str("category"), r.str("kind")
	if category != "" && category != "machine" && category != "monitoring" {
		return usageErr("--category must be machine or monitoring")
	}
	if severity != "" && severity != "info" && severity != "warning" && severity != "critical" {
		return usageErr("--severity must be info, warning or critical")
	}
	res, err := r.client.ListAlerts(r.ctx, api.AlertFilter{DeviceID: deviceID, OpenOnly: r.boolean("open"), Category: category, Severity: severity, Kind: kind}, limit)
	if err != nil {
		return err
	}
	alerts, err := api.DecodeAll[api.Alert](res.Items)
	if err != nil {
		return err
	}
	keepItems, kept := res.Items, alerts
	r.warnMore(res, "alerts")
	if r.format != formatTable {
		return writeList(r.out(), keepItems, r.format)
	}
	names := r.deviceNames()
	t := &table{Headers: []string{"TRIGGERED", "SEVERITY", "STATE", "MACHINE", "MESSAGE", "ID"}}
	cut := 70
	if r.boolean("wide") || !r.app.io.OutTTY {
		cut = 1 << 20
	}
	for _, a := range kept {
		state, style := "open", "red"
		if a.Resolved {
			state, style = "resolved", "dim"
		}
		machine := a.DeviceID
		if n, ok := names[a.DeviceID]; ok {
			machine = n
		}
		t.add(plain(timeFmt(a.TriggeredAt, r.loc())), cell{Text: first(strPtr(a.Severity), "-"), Style: sevStyle(strPtr(a.Severity))},
			cell{Text: state, Style: style}, plain(machine), plain(clip(first(strPtr(a.Message), "-"), cut)), plain(a.ID))
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

func runAlertsShow(r *runCtx) error {
	id := strings.ToLower(r.args[0])
	if !api.IsUUID(id) {
		return usageErr("%q is not an alert id (they look like 0b6c1f0e-1111-4222-8333-444455556666)", r.args[0])
	}
	raw, err := r.client.GetAlertRaw(r.ctx, id)
	if err != nil {
		return err
	}
	var alert api.Alert
	if err := json.Unmarshal(raw, &alert); err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var extra struct {
		FirstSeen api.Time `json:"first_seen_at"`
		LastSeen  api.Time `json:"last_seen_at"`
	}
	_ = json.Unmarshal(raw, &extra)
	names := r.deviceNames()
	k := &kv{}
	k.add("id", alert.ID)
	machine := alert.DeviceID
	if n, ok := names[alert.DeviceID]; ok {
		machine = n + " (" + alert.DeviceID + ")"
	}
	k.add("machine", machine)
	k.addStyled("severity", first(strPtr(alert.Severity), "-"), sevStyle(strPtr(alert.Severity)))
	if alert.Resolved {
		k.add("state", "resolved at "+timeFmt(alert.ResolvedAt, r.loc()))
	} else {
		k.addStyled("state", "open", "red")
	}
	k.add("category", first(alert.Category, "-"))
	k.add("kind", str(alert.Kind))
	k.add("sensor", str(alert.SensorKey))
	k.add("message", first(strPtr(alert.Message), "-"))
	k.add("triggered", timeFmt(alert.TriggeredAt, r.loc()))
	if !extra.FirstSeen.IsZero() {
		k.add("first seen", timeFmt(extra.FirstSeen, r.loc()))
	}
	if !extra.LastSeen.IsZero() {
		k.add("last seen", timeFmt(extra.LastSeen, r.loc()))
	}
	k.add("occurrences", fmt.Sprint(alert.Occurrences))
	if alert.LastValue != nil {
		k.add("last value", fmt.Sprint(*alert.LastValue))
	}
	if alert.PeakValue != nil {
		k.add("peak value", fmt.Sprint(*alert.PeakValue))
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

// confirm asks a yes or no question. It never asks without a terminal.
func (r *runCtx) confirm(question string) error {
	if r.boolean("yes") {
		return nil
	}
	if !r.app.io.InTTY {
		return usageErr("this needs confirmation and standard input is not a terminal, so it will not ask: pass --yes to go ahead")
	}
	fmt.Fprintf(r.errw(), "%s [y/N] ", question)
	line, _ := bufio.NewReader(r.app.io.In).ReadString('\n')
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "y", "yes":
		return nil
	}
	return newExit(ExitFailure, "not confirmed: nothing was changed")
}

func runAlertsResolve(r *runCtx) error {
	id := strings.ToLower(r.args[0])
	if !api.IsUUID(id) {
		return usageErr("%q is not an alert id (they look like 0b6c1f0e-1111-4222-8333-444455556666)", r.args[0])
	}
	if err := r.confirm(fmt.Sprintf("Resolve alert %s?", id)); err != nil {
		return err
	}
	raw, err := r.client.ResolveAlert(r.ctx, id)
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	r.info("Alert %s is resolved.", id)
	return nil
}
