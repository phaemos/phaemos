package cli

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:    []string{"doctor"},
		summary: "check the profile end to end and say what is wrong",
		desc: "Checks, in order: the config file, the address, that the server answers over TLS, the difference between this machine's clock " +
			"and the server's Date header, that the API token is valid and its scope and expiry, that the token can read and (when a device key " +
			"is set in PHAEMOS_DEVICE_KEY or --key) that the device key is accepted. Every check runs. The exit code is the first failing " +
			"check's code (3 for a token or key that is refused, 8 for a server that cannot be reached, 2 for a bad address or file, 1 for a " +
			"clock that is far out) and 0 when all pass.",
		examples: []string{"phaemosctl doctor", "phaemosctl doctor --profile staging --output json"},
		flags: func(fs *flag.FlagSet) {
			fs.String("key", "", "also check this device key (prefer PHAEMOS_DEVICE_KEY)")
		},
		noConfig: true, allowsNewProfile: true, timeout: 30 * time.Second,
		run: runDoctor,
	})
	register(&command{
		path:    []string{"devices", "accept-counter"},
		summary: "accept a new boot and seq counter for a device whose flash was wiped",
		desc: "A device that has sent a (boot, seq) pair must always send a newer one, so a device whose flash was wiped is refused (409) until " +
			"this is done. It makes the API forget the last pair it accepted for the device: the next post sets the new start. Do it only " +
			"after a wipe. If the counter rose too fast instead (the API reports a counter jump), someone else may hold the device key: " +
			"the API advises rotating the key as well and a token can never rotate a key (that needs a signed-in person's fresh proof on the " +
			"dashboard). It asks you to confirm and needs a token of the admin scope.",
		examples: []string{"phaemosctl devices accept-counter press-01", "phaemosctl devices accept-counter press-01 --yes"},
		args:     "<device>", minArgs: 1, maxArgs: 1, needsToken: true, scope: "admin",
		flags: func(fs *flag.FlagSet) { fs.Bool("yes", false, "do not ask for confirmation") },
		run:   runAcceptCounter,
	})
	register(&command{
		path:       []string{"windows", "list"},
		summary:    "list maintenance windows",
		desc:       "Lists maintenance windows (times when alerts are silenced) for the devices you may read and for the whole fleet.",
		examples:   []string{"phaemosctl windows list", "phaemosctl windows list --output json"},
		flags:      func(fs *flag.FlagSet) { limitFlag(fs) },
		needsToken: true,
		run:        runWindowsList,
	})
	register(&command{
		path:    []string{"windows", "start"},
		summary: "silence a device's alerts for a while",
		desc: "Starts a maintenance window now for a device (by id or name) that lasts --for (a duration such as 90m, 2h or 1d). Alerts for " +
			"the device are suppressed until it ends. It asks you to confirm and needs a token of the admin scope. End it early with windows end.",
		examples: []string{"phaemosctl windows start press-01 --for 2h --label \"bearing swap\"", "phaemosctl windows start press-01 --for 90m --yes"},
		args:     "<device>", minArgs: 1, maxArgs: 1, needsToken: true, scope: "admin",
		flags: func(fs *flag.FlagSet) {
			fs.Duration("for", 0, "how long the window lasts (required, for example 2h)")
			fs.String("label", "Maintenance (phaemosctl)", "what the window is for")
			fs.Bool("yes", false, "do not ask for confirmation")
		},
		run: runWindowsStart,
	})
	register(&command{
		path:     []string{"windows", "end"},
		summary:  "end a maintenance window now",
		desc:     "Ends a maintenance window by moving its end to now, so alerts are raised again. Repeating it is safe. It needs a token of the admin scope.",
		examples: []string{"phaemosctl windows end 0b6c1f0e-1111-4222-8333-444455556666", "phaemosctl windows list --output json | jq -r '.[0].id'"},
		args:     "<id>", minArgs: 1, maxArgs: 1, needsToken: true, scope: "admin",
		run: runWindowsEnd,
	})
	register(&command{
		path:    []string{"tokens", "list"},
		summary: "list your API tokens",
		desc: "Lists the account's tokens that are not revoked, newest first, with their scope, expiry and when each was last used. The token " +
			"you are using is marked with a star. A token cannot make or revoke other tokens: that is done on the profile page of the dashboard.",
		examples:   []string{"phaemosctl tokens list", "phaemosctl tokens list --output json"},
		needsToken: true,
		run:        runTokensList,
	})
	register(&command{
		path:    []string{"tokens", "revoke-current"},
		summary: "revoke the token this tool is using and forget it",
		desc: "Revokes the token in use on the server and removes it from the config file when it came from there. A token may revoke itself and " +
			"nothing else. Use it when a machine is retired or a token may have leaked from it: another token is revoked from the dashboard.",
		examples:   []string{"phaemosctl tokens revoke-current", "phaemosctl tokens revoke-current --yes"},
		needsToken: true,
		flags:      func(fs *flag.FlagSet) { fs.Bool("yes", false, "do not ask for confirmation") },
		run:        runTokensRevokeCurrent,
	})
}

// ---- doctor ----

type check struct {
	Name   string `json:"name"`
	Status string `json:"status"` // ok, warn, fail or skip
	Detail string `json:"detail"`
	Exit   int    `json:"exit,omitempty"`
}

func runDoctor(r *runCtx) error {
	var checks []check
	add := func(name, status, detail string, exit int) {
		checks = append(checks, check{Name: name, Status: status, Detail: detail, Exit: exit})
	}
	// the config
	if err := r.app.loadConfig(); err != nil {
		add("config file", "fail", err.Error(), ExitUsage)
		r.app.cfg = newConfig()
	} else if r.app.path == "" {
		add("config file", "warn", "no place for a config file (set PHAEMOS_CONFIG, XDG_CONFIG_HOME or HOME): only flags and the environment are used", 0)
	} else {
		add("config file", "ok", r.app.path, 0)
	}
	resolveErr := r.app.resolve(r)
	if resolveErr != nil {
		ee := classify(resolveErr)
		add("address and profile", "fail", ee.Message, ee.Code)
		return finishDoctor(r, checks)
	}
	add("address and profile", "ok", fmt.Sprintf("profile %s, %s", r.profile, r.url), 0)
	if r.slashStripped {
		add("address slash", "warn", "the configured address ends in a slash. The tool strips it because the server answers 404 for a path with a trailing slash. Remove it from the setting (PHAEMOS_URL, --url or the config file)", 0)
	}
	if strings.HasPrefix(r.url, "https://") {
		add("transport", "ok", "https: the server's certificate is checked", 0)
	} else {
		add("transport", "warn", "plain http to a local address: nothing is encrypted", 0)
	}
	// the server answers and the clock
	info, err := r.client.ServerInfo(r.ctx)
	switch {
	case err != nil:
		ee := classify(err)
		detail := ee.Message
		if strings.Contains(strings.ToLower(err.Error()), "certificate") {
			detail = "the server's certificate was refused: " + detail
		}
		var ae *api.Error
		if errors.As(err, &ae) && ae.Status == 404 {
			detail += ". The address is probably wrong: it must be the base address only (for example https://api.example.org) with no path and no trailing slash, because the server answers 404 for a path it does not know and never redirects"
		}
		add("server reachable", "fail", detail, ee.Code)
		add("clock", "skip", "needs the server", 0)
	default:
		reach := r.url + " answered /status"
		if info.Version != "" {
			reach += ", server version " + info.Version
		}
		add("server reachable", "ok", reach, 0)
		if info.Clock.IsZero() {
			add("clock", "skip", "the server sent no time", 0)
			break
		}
		abs := r.app.io.Now().Sub(info.Clock).Abs()
		switch {
		case abs > 5*time.Minute:
			add("clock", "fail", fmt.Sprintf("this machine's clock differs from the server's (%s) by %s: tokens and certificates are judged by time", info.ClockSource, abs.Round(time.Second)), ExitFailure)
		case abs > time.Minute:
			add("clock", "warn", fmt.Sprintf("this machine's clock differs from the server's (%s) by %s", info.ClockSource, abs.Round(time.Second)), 0)
		default:
			add("clock", "ok", fmt.Sprintf("within %s of the server (%s)", max(abs, time.Second).Round(time.Second), info.ClockSource), 0)
		}
	}
	// the token
	switch {
	case r.token == "":
		add("API token", "fail", "not signed in: run phaemosctl auth login or set PHAEMOS_TOKEN", ExitNotSignedIn)
	default:
		raw, err := r.client.WhoamiRaw(r.ctx)
		if err != nil {
			ee := classify(err)
			add("API token", "fail", ee.Message, ee.Code)
			break
		}
		who, _ := api.ParseWhoami(raw)
		detail := fmt.Sprintf("%s, scope %s", first(who.Role, "account"), first(who.Scope, "unknown"))
		status := "ok"
		if !who.ExpiresAt.IsZero() {
			left := who.ExpiresAt.Sub(r.app.io.Now())
			switch {
			case left <= 0:
				add("API token", "fail", detail+", expired", ExitNotSignedIn)
				status = ""
			case left < expiryWarning:
				status = "warn"
				detail += fmt.Sprintf(", expires in %d days", int(left.Hours()/24))
			default:
				detail += fmt.Sprintf(", expires in %d days", int(left.Hours()/24))
			}
		}
		if status != "" {
			add("API token", status, detail, 0)
		}
		if _, err := r.client.HealthRaw(r.ctx); err != nil {
			ee := classify(err)
			add("token can read", "fail", ee.Message, ee.Code)
		} else {
			add("token can read", "ok", "the health summary was read", 0)
		}
	}
	// the device key, when one is set
	key := first(r.str("key"), r.app.io.Getenv("PHAEMOS_DEVICE_KEY"), r.app.io.Getenv("PHAEMOS_API_KEY"))
	if key == "" {
		add("device key", "skip", "none set (PHAEMOS_DEVICE_KEY)", 0)
	} else {
		dc := api.New(r.url, key)
		dc.Clock, dc.UserAgent = r.app.io.Clock, "phaemosctl/"+Version
		if r.app.io.HTTP != nil {
			dc.HTTP = r.app.io.HTTP
		}
		_, err := dc.Do(r.ctx, api.Request{Method: http.MethodGet, Path: "/api/v1/firmware/latest", UseKey: true, NoRetry: true})
		var ae *api.Error
		switch {
		case err == nil, errors.As(err, &ae) && ae.Status == 404:
			add("device key", "ok", "the server accepted the key (nothing was sent but a read)", 0)
		case errors.As(err, &ae) && (ae.Status == 401 || ae.Status == 403):
			add("device key", "fail", "the server refused the device key", ExitNotSignedIn)
		default:
			ee := classify(err)
			add("device key", "fail", ee.Message, ee.Code)
		}
	}
	return finishDoctor(r, checks)
}

func finishDoctor(r *runCtx, checks []check) error {
	var firstFail *check
	for i := range checks {
		if checks[i].Status == "fail" && firstFail == nil {
			firstFail = &checks[i]
		}
	}
	if r.format != formatTable {
		raw, _ := json.Marshal(map[string]any{"ok": firstFail == nil, "checks": checks})
		if err := r.emitRaw(raw); err != nil {
			return err
		}
	} else {
		t := &table{Headers: []string{"CHECK", "RESULT", "DETAIL"}}
		for _, c := range checks {
			style := map[string]string{"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim"}[c.Status]
			t.add(plain(c.Name), cell{Text: c.Status, Style: style}, plain(c.Detail))
		}
		renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	}
	if firstFail != nil {
		code := firstFail.Exit
		if code == 0 {
			code = ExitFailure
		}
		return &exitError{Code: code, Kind: kinds[code], Message: fmt.Sprintf("%s: %s", firstFail.Name, firstFail.Detail), silent: true}
	}
	return nil
}

// ---- devices accept-counter ----

func runAcceptCounter(r *runCtx) error {
	dev, _, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	question := fmt.Sprintf("Accept a new counter for %s? Its last accepted boot and seq are forgotten and its next post sets the new start. Do this only after its flash was wiped.", dev.Name)
	if dev.ReplayProtected && dev.LastBoot != nil && dev.LastSeq != nil {
		question += fmt.Sprintf(" Last accepted: boot %d, seq %d.", *dev.LastBoot, *dev.LastSeq)
	}
	if err := r.confirm(question); err != nil {
		return err
	}
	raw, err := r.client.AcceptCounter(r.ctx, dev.ID)
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	r.info("Accepted a new counter for %s.", dev.Name)
	var after struct {
		Recovery *string `json:"replay_recovery"`
		Warning  *string `json:"replay_warning"`
	}
	_ = json.Unmarshal(raw, &after)
	if after.Warning != nil {
		r.warn("%s", *after.Warning)
	}
	if after.Recovery != nil {
		r.info("The API advises: %s", *after.Recovery)
	}
	return nil
}

// ---- windows ----

type window struct {
	ID       string   `json:"id"`
	Label    *string  `json:"label"`
	StartAt  api.Time `json:"start_at"`
	EndAt    api.Time `json:"end_at"`
	Suppress *bool    `json:"suppress_alerts"`
	DeviceID *string  `json:"device_id"`
}

func runWindowsList(r *runCtx) error {
	limit, err := r.limit()
	if err != nil {
		return err
	}
	res, err := r.client.ListWindows(r.ctx, limit)
	if err != nil {
		return err
	}
	r.warnMore(res, "windows")
	if r.format != formatTable {
		return writeList(r.out(), res.Items, r.format)
	}
	windows, err := api.DecodeAll[window](res.Items)
	if err != nil {
		return err
	}
	names := r.deviceNames()
	t := &table{Headers: []string{"LABEL", "DEVICE", "START", "END", "STATE", "ID"}}
	now := r.app.io.Now()
	for _, w := range windows {
		dev := "whole fleet"
		if w.DeviceID != nil {
			dev = first(names[*w.DeviceID], *w.DeviceID)
		}
		state, style := "ended", "dim"
		switch {
		case now.Before(w.StartAt.Time):
			state, style = "coming", ""
		case now.Before(w.EndAt.Time):
			state, style = "active", "yellow"
		}
		t.add(plain(first(strPtr(w.Label), "-")), plain(dev), plain(timeFmt(w.StartAt, r.loc())), plain(timeFmt(w.EndAt, r.loc())), cell{Text: state, Style: style}, plain(w.ID))
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

// parseSpan reads a duration such as 90m or 2h and also 1d.
func parseSpan(text string) (time.Duration, error) {
	if strings.HasSuffix(text, "d") {
		if n, err := strconv.Atoi(strings.TrimSuffix(text, "d")); err == nil {
			return time.Duration(n) * 24 * time.Hour, nil
		}
	}
	return time.ParseDuration(text)
}

func runWindowsStart(r *runCtx) error {
	span := r.duration("for")
	if span <= 0 {
		return usageErr("--for is required: how long the window lasts, for example 2h")
	}
	if span > 31*24*time.Hour {
		return usageErr("--for is at most 31 days")
	}
	dev, _, err := r.client.ResolveDevice(r.ctx, r.args[0])
	if err != nil {
		return err
	}
	if err := r.confirm(fmt.Sprintf("Silence alerts for %s for %s?", dev.Name, span)); err != nil {
		return err
	}
	now := r.app.io.Now()
	// one key for this run: a retry after a time-out cannot make two windows
	key, err := r.app.idempotencyKey()
	if err != nil {
		return err
	}
	raw, err := r.client.CreateWindow(r.ctx, r.str("label"), now, now.Add(span), dev.ID, key)
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var w window
	_ = json.Unmarshal(raw, &w)
	r.info("Alerts for %s are silenced until %s. End it early with: phaemosctl windows end %s", dev.Name, timeFmt(api.Time{Time: now.Add(span)}, r.loc()), w.ID)
	return nil
}

func runWindowsEnd(r *runCtx) error {
	if !api.IsUUID(strings.ToLower(r.args[0])) {
		return usageErr("%q is not a window id", r.args[0])
	}
	raw, err := r.client.EndWindow(r.ctx, strings.ToLower(r.args[0]), r.app.io.Now())
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	r.info("The window has ended: alerts are raised again.")
	return nil
}

// ---- tokens ----

func runTokensList(r *runCtx) error {
	raw, err := r.client.TokensRaw(r.ctx)
	if err != nil {
		return err
	}
	if r.format == formatJSON {
		return r.emitRaw(raw)
	}
	var items []json.RawMessage
	if err := json.Unmarshal(raw, &items); err != nil {
		return err
	}
	if r.format == formatJSONL {
		return writeList(r.out(), items, formatJSONL)
	}
	tokens, err := api.DecodeAll[api.TokenInfo](items)
	if err != nil {
		return err
	}
	current := ""
	if who, err := r.client.WhoamiRaw(r.ctx); err == nil {
		w, _ := api.ParseWhoami(who)
		current = w.TokenID
	}
	t := &table{Headers: []string{"", "NAME", "SCOPE", "CREATED", "EXPIRES", "LAST USED", "ID"}}
	for _, tk := range tokens {
		mark := ""
		if tk.ID == current {
			mark = "*"
		}
		used := "never"
		if !tk.LastUsedAt.IsZero() {
			used = timeFmt(tk.LastUsedAt, r.loc())
		}
		t.add(plain(mark), plain(tk.Name), plain(tk.Scope), plain(timeFmt(tk.CreatedAt, r.loc())), plain(timeFmt(tk.ExpiresAt, r.loc())), plain(used), plain(tk.ID))
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

func runTokensRevokeCurrent(r *runCtx) error {
	if err := r.confirm("Revoke the token this tool is using? It stops working at once and cannot be restored."); err != nil {
		return err
	}
	if err := r.client.RevokeCurrentToken(r.ctx); err != nil {
		return err
	}
	prof := r.app.cfg.Profiles[r.profile]
	removed := false
	if prof != nil && prof.Token == r.token {
		prof.Token, prof.TokenID, prof.TokenName, prof.TokenScope = "", "", "", ""
		prof.TokenExpires = time.Time{}
		if err := r.saveConfig(); err == nil {
			removed = true
		}
	}
	if r.format != formatTable {
		raw, _ := json.Marshal(map[string]any{"revoked": true, "removed_from_config": removed})
		return r.emitRaw(raw)
	}
	r.info("The token is revoked.")
	if removed {
		r.info("It was removed from the config file.")
	} else if r.app.io.Getenv("PHAEMOS_TOKEN") != "" {
		r.info("PHAEMOS_TOKEN is still set in the environment: unset it in your shell.")
	}
	return nil
}
