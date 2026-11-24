package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:    []string{"status"},
		summary: "the server's status and who you are when signed in",
		desc: "Shows the public status of the server (the API, the database, Redis and the anomaly model). When a token is set " +
			"it also asks who the token is and shows the account's role and the token's scope and expiry. With --output json " +
			"the answer is one document with the server's status under \"status\" and the answer to whoami under \"whoami\" " +
			"(null without a token).",
		examples: []string{"phaemosctl status", "phaemosctl status --output json"},
		maxArgs:  0,
		run:      runStatus,
	})
	register(&command{
		path:     []string{"health"},
		summary:  "the monitoring health summary of the fleet",
		desc:     "Shows how many machines you may read, how many are online, offline and late, the open alerts and tickets and the health score.",
		examples: []string{"phaemosctl health", "phaemosctl health --output json | jq .health_score"},
		maxArgs:  0, needsToken: true,
		run: runHealth,
	})
	register(&command{
		path:    []string{"model", "status"},
		summary: "the anomaly model's state and last retrain",
		desc: "Shows what model is in service, when it was trained, when the next nightly retrain runs and the outcome of the " +
			"last retrain (accepted or refused, with the reason).",
		examples: []string{"phaemosctl model status", "phaemosctl model status --output json"},
		maxArgs:  0, needsToken: true,
		run: runModelStatus,
	})
	register(&command{
		path:    []string{"version"},
		summary: "the tool's version (also --version) and the server's with --server",
		desc: "Shows the version this tool was built as. It works offline. With --server it also asks the server: whether it answers and its " +
			"version, which is read from its interactive docs schema. A production server turns that off, so the server's version is often " +
			"not published.",
		examples: []string{"phaemosctl version", "phaemosctl version --server --url https://api.example.org"},
		maxArgs:  0,
		timeout:  15 * time.Second,
		noConfig: true, allowsNewProfile: true,
		flags: func(fs *flag.FlagSet) { fs.Bool("server", false, "also ask the server") },
		run:   runVersion,
	})
	register(&command{
		path:     []string{"completion"},
		summary:  "print a shell completion script (bash, zsh or fish)",
		desc:     "Prints a script that completes command names and options. Load it in your shell's start-up file.",
		examples: []string{"source <(phaemosctl completion bash)", "phaemosctl completion fish > ~/.config/fish/completions/phaemosctl.fish"},
		args:     "bash|zsh|fish", minArgs: 1, maxArgs: 1, noConfig: true,
		run: runCompletion,
	})
}

func (r *runCtx) emitRaw(raw []byte) error { return compactJSON(r.out(), raw) }

func runStatus(r *runCtx) error {
	raw, err := r.client.StatusRaw(r.ctx)
	if err != nil {
		return err
	}
	var whoRaw []byte
	var whoErr error
	if r.token != "" {
		whoRaw, whoErr = r.client.WhoamiRaw(r.ctx)
	}
	if r.format != formatTable {
		var buf bytes.Buffer
		buf.WriteString(`{"status":`)
		buf.Write(bytes.TrimSpace(raw))
		buf.WriteString(`,"whoami":`)
		if whoRaw != nil {
			buf.Write(bytes.TrimSpace(whoRaw))
		} else {
			buf.WriteString("null")
		}
		buf.WriteString("}")
		if err := r.emitRaw(buf.Bytes()); err != nil {
			return err
		}
		return whoErr
	}
	var st map[string]any
	_ = json.Unmarshal(raw, &st)
	k := &kv{}
	k.add("server", r.url)
	for _, key := range []string{"status", "api", "database", "redis", "model", "updated_at"} {
		if v, ok := st[key]; ok {
			style := ""
			text := fmt.Sprint(v)
			if key == "updated_at" {
				var t api.Time
				quoted, _ := json.Marshal(text)
				if t.UnmarshalJSON(quoted) == nil && !t.IsZero() {
					text = timeFmt(t, r.loc())
				}
			} else if text == "ok" || text == "operational" {
				style = "green"
			} else if key != "model" {
				style = "red"
			}
			k.addStyled(key, text, style)
		}
	}
	if whoRaw != nil {
		w, _ := api.ParseWhoami(whoRaw)
		addWho(k, w, r)
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return whoErr
}

func addWho(k *kv, w api.Whoami, r *runCtx) {
	k.add("signed in as", first(w.Role, "-"))
	k.add("signed in with", w.SignedIn)
	if w.TokenName != "" || w.TokenID != "" {
		k.add("token", strings.TrimSpace(w.TokenName+" ("+w.TokenID+")"))
	}
	if w.Scope != "" {
		k.add("scope", w.Scope)
	}
	if !w.ExpiresAt.IsZero() {
		left := w.ExpiresAt.Sub(r.app.io.Now())
		text := timeFmt(w.ExpiresAt, r.loc())
		style := ""
		switch {
		case left <= 0:
			text += " (expired)"
			style = "red"
		case left < expiryWarning:
			text += fmt.Sprintf(" (in %d days)", int(left.Hours()/24))
			style = "yellow"
		default:
			text += fmt.Sprintf(" (in %d days)", int(left.Hours()/24))
		}
		k.addStyled("expires", text, style)
	}
}

func runHealth(r *runCtx) error {
	raw, err := r.client.HealthRaw(r.ctx)
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var h api.HealthSummary
	if err := json.Unmarshal(raw, &h); err != nil {
		return err
	}
	k := &kv{}
	k.add("machines", fmt.Sprint(h.TotalDevices))
	k.add("online", fmt.Sprint(h.Online))
	k.add("offline", fmt.Sprint(h.Offline))
	for _, state := range []string{"online", "late", "offline"} {
		if n, ok := h.LinkStates[state]; ok {
			k.add("link "+state, fmt.Sprint(n))
		}
	}
	k.add("open alerts", fmt.Sprint(h.ActiveAlerts))
	k.add("open tickets", fmt.Sprint(h.OpenTickets))
	style := "green"
	if h.HealthScore < 80 {
		style = "yellow"
	}
	if h.HealthScore < 50 {
		style = "red"
	}
	k.addStyled("health score", fmt.Sprintf("%d / 100", h.HealthScore), style)
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

func runModelStatus(r *runCtx) error {
	raw, err := r.client.ModelRaw(r.ctx)
	if err != nil {
		return err
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var m api.MLStatus
	if err := json.Unmarshal(raw, &m); err != nil {
		return err
	}
	k := &kv{}
	style := "green"
	if m.State != "ok" {
		style = "yellow"
	}
	if m.State == "error" {
		style = "red"
	}
	k.addStyled("state", m.State, style)
	k.add("trained", timeFmt(m.TrainedAt, r.loc()))
	if m.Schedule.NightlyUTC != "" {
		k.add("nightly retrain (UTC)", m.Schedule.NightlyUTC)
	}
	if !m.Schedule.NextAt.IsZero() {
		k.add("next retrain", timeFmt(m.Schedule.NextAt, r.loc()))
	}
	if m.LastRetrain != nil {
		k.add("last retrain", m.LastRetrain.Status+" ("+first(m.LastRetrain.Trigger, "-")+") at "+timeFmt(m.LastRetrain.FinishedAt, r.loc()))
		k.add("summary", clip(m.LastRetrain.Summary, 200))
	} else {
		k.add("last retrain", "none yet")
	}
	for _, mod := range m.Models {
		rate := "-"
		if mod.FalseAlertsPerWeek != nil {
			rate = fmt.Sprintf("%.2f false alerts a week", *mod.FalseAlertsPerWeek)
		}
		legacy := ""
		if mod.Legacy {
			legacy = ", legacy"
		}
		k.add("model "+mod.Scope, mod.Key+" ("+rate+legacy+")")
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

func runVersion(r *runCtx) error {
	version := Version
	if r.app.io.Version != "" {
		version = r.app.io.Version
	}
	body := map[string]any{"version": version}
	if Commit != "" {
		body["commit"] = Commit
	}
	k := &kv{}
	k.add("phaemosctl", version)
	if Commit != "" {
		k.add("commit", Commit)
	}
	// the server is asked only when --server is given: a version check should work offline and not need a profile
	if r.boolean("server") {
		if err := r.app.loadConfig(); err != nil {
			return usageErr("%s", err.Error())
		}
		if err := r.app.resolve(r); err != nil {
			return err
		}
		server := r.client.ServerVersion(r.ctx)
		_, statusErr := r.client.StatusRaw(r.ctx)
		reach := "reachable"
		if statusErr != nil {
			var ae *api.Error
			if errors.As(statusErr, &ae) && ae.Status != 0 {
				reach = fmt.Sprintf("answered %d", ae.Status)
			} else {
				reach = "not reachable"
			}
		}
		body["server"], body["server_reachable"] = r.url, statusErr == nil
		k.add("server", r.url+" ("+reach+")")
		if server != "" {
			body["server_version"] = server
			k.add("server version", server)
		} else {
			k.add("server version", "not published by this server")
		}
	}
	if r.format != formatTable {
		raw, _ := json.Marshal(body)
		return r.emitRaw(raw)
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

// ---- completion ----

func runCompletion(r *runCtx) error {
	var b strings.Builder
	switch r.args[0] {
	case "bash":
		completionBash(&b)
	case "zsh":
		completionZsh(&b)
	case "fish":
		completionFish(&b)
	default:
		return usageErr("the shell must be bash, zsh or fish")
	}
	_, err := r.out().Write([]byte(b.String()))
	return err
}

func optionNames(c *command) []string {
	fs := flag.NewFlagSet("x", flag.ContinueOnError)
	(&globals{}).register(fs)
	if c.flags != nil {
		c.flags(fs)
	}
	var names []string
	fs.VisitAll(func(f *flag.Flag) {
		if len(f.Name) > 1 {
			names = append(names, "--"+f.Name)
		}
	})
	sort.Strings(names)
	return names
}

func completionBash(b *strings.Builder) {
	n := nouns()
	var nounNames []string
	for noun := range n {
		nounNames = append(nounNames, noun)
	}
	var singles []string
	for _, c := range commands {
		if len(c.path) == 1 {
			singles = append(singles, c.path[0])
		}
	}
	sort.Strings(nounNames)
	sort.Strings(singles)
	b.WriteString("# bash completion for phaemosctl\n_phaemosctl() {\n  local cur=\"${COMP_WORDS[COMP_CWORD]}\" first=\"${COMP_WORDS[1]}\" second=\"${COMP_WORDS[2]}\"\n  local words=\"\"\n")
	fmt.Fprintf(b, "  if [ \"$COMP_CWORD\" -eq 1 ]; then\n    words=\"%s help\"\n", strings.Join(append(append([]string{}, nounNames...), singles...), " "))
	b.WriteString("  elif [ \"$COMP_CWORD\" -eq 2 ]; then\n    case \"$first\" in\n")
	for _, noun := range nounNames {
		var verbs []string
		for _, c := range n[noun] {
			verbs = append(verbs, c.path[1])
		}
		sort.Strings(verbs)
		fmt.Fprintf(b, "      %s) words=\"%s\" ;;\n", noun, strings.Join(verbs, " "))
	}
	b.WriteString("      completion) words=\"bash zsh fish\" ;;\n    esac\n  fi\n")
	b.WriteString("  if [ -z \"$words\" ] || [[ \"$cur\" == -* ]]; then\n    case \"$first $second\" in\n")
	for _, c := range sortedByName() {
		fmt.Fprintf(b, "      \"%s\"*) words=\"%s\" ;;\n", c.name(), strings.Join(optionNames(c), " "))
	}
	b.WriteString("    esac\n  fi\n  COMPREPLY=( $(compgen -W \"$words\" -- \"$cur\") )\n}\ncomplete -F _phaemosctl phaemosctl\n")
}

func sortedByName() []*command {
	list := append([]*command(nil), commands...)
	sort.Slice(list, func(i, j int) bool { return list[i].name() < list[j].name() })
	return list
}

func completionZsh(b *strings.Builder) {
	b.WriteString("#compdef phaemosctl\n# zsh completion for phaemosctl\n_phaemosctl() {\n  local -a nouns verbs\n  if (( CURRENT == 2 )); then\n    nouns=(")
	seen := map[string]bool{}
	var tops []string
	for _, c := range sortedByName() {
		if !seen[c.path[0]] {
			seen[c.path[0]] = true
			tops = append(tops, c.path[0])
		}
	}
	b.WriteString(strings.Join(tops, " ") + " help)\n    compadd -a nouns\n    return\n  fi\n  case $words[2] in\n")
	for noun, list := range nouns() {
		var verbs []string
		for _, c := range list {
			verbs = append(verbs, c.path[1])
		}
		sort.Strings(verbs)
		fmt.Fprintf(b, "    %s) (( CURRENT == 3 )) && { verbs=(%s); compadd -a verbs; return } ;;\n", noun, strings.Join(verbs, " "))
	}
	b.WriteString("    completion) (( CURRENT == 3 )) && { verbs=(bash zsh fish); compadd -a verbs; return } ;;\n  esac\n  local -a opts\n  opts=(")
	set := map[string]bool{}
	for _, c := range commands {
		for _, o := range optionNames(c) {
			set[o] = true
		}
	}
	var all []string
	for o := range set {
		all = append(all, o)
	}
	sort.Strings(all)
	b.WriteString(strings.Join(all, " ") + ")\n  compadd -a opts\n}\n_phaemosctl \"$@\"\n")
}

func completionFish(b *strings.Builder) {
	b.WriteString("# fish completion for phaemosctl\ncomplete -c phaemosctl -f\n")
	n := nouns()
	var nounNames []string
	for noun := range n {
		nounNames = append(nounNames, noun)
	}
	sort.Strings(nounNames)
	for _, c := range sortedByName() {
		if len(c.path) == 1 {
			fmt.Fprintf(b, "complete -c phaemosctl -n '__fish_use_subcommand' -a %s -d '%s'\n", c.path[0], strings.ReplaceAll(c.summary, "'", ""))
		}
	}
	for _, noun := range nounNames {
		fmt.Fprintf(b, "complete -c phaemosctl -n '__fish_use_subcommand' -a %s -d '%s'\n", noun, nounSummary[noun])
		for _, c := range n[noun] {
			fmt.Fprintf(b, "complete -c phaemosctl -n '__fish_seen_subcommand_from %s; and not __fish_seen_subcommand_from %s' -a %s -d '%s'\n",
				noun, c.path[1], c.path[1], strings.ReplaceAll(c.summary, "'", ""))
		}
	}
	b.WriteString("complete -c phaemosctl -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'\n")
	set := map[string]bool{}
	for _, c := range commands {
		for _, o := range optionNames(c) {
			set[strings.TrimPrefix(o, "--")] = true
		}
	}
	var all []string
	for o := range set {
		all = append(all, o)
	}
	sort.Strings(all)
	for _, o := range all {
		fmt.Fprintf(b, "complete -c phaemosctl -l %s\n", o)
	}
}
