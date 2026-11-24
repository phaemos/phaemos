package cli

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"sort"
	"strings"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:    []string{"auth", "login"},
		summary: "store an API token for a profile after proving it works",
		desc: "Reads an API token (it starts with pht_) and asks the server who it is, to prove it. When that works the token is " +
			"stored in the config file (mode 0600) under the profile. On a terminal the token is typed at a prompt that does not echo. " +
			"With no terminal it is read from one line on standard input. It is never taken from a flag, never printed and never put in an error. " +
			"A token is made on the profile page of the dashboard by a signed-in person, who proves it with their password (and code). " +
			"This tool can never make, list for others or revoke a token: the API only lets a signed-in session do that.",
		examples: []string{
			"phaemosctl auth login",
			"phaemosctl auth login --profile staging --url https://staging.example.org",
			"pass show phaemos/token | phaemosctl auth login",
		},
		noConfig: false, allowsNewProfile: true,
		run: runLogin,
	})
	register(&command{
		path:    []string{"auth", "status"},
		summary: "who the token is, its scope and when it expires",
		desc: "Asks the server who the current token is and shows the account's role, the token's name, scope and expiry. A warning " +
			"is printed when the token expires within 14 days.",
		examples:   []string{"phaemosctl auth status", "phaemosctl auth status --output json"},
		needsToken: true,
		run:        runAuthStatus,
	})
	register(&command{
		path:    []string{"auth", "logout"},
		summary: "remove the stored token from the config file",
		desc: "Removes the token of the profile from the config file. It does not revoke the token on the server: a token that was " +
			"copied somewhere else still works until it is revoked on the dashboard or expires. A token set in PHAEMOS_TOKEN is not " +
			"touched: unset it in your shell.",
		examples: []string{"phaemosctl auth logout", "phaemosctl auth logout --profile staging"},
		run:      runLogout,
	})
	register(&command{
		path:    []string{"config", "set"},
		summary: "set a setting in the config file (url or default-profile)",
		desc: "Sets the API address of a profile (--profile, else the default profile) or the name of the default profile. Tokens are " +
			"never set here: use auth login. The file is kept at mode 0600 in a folder of mode 0700.",
		examples: []string{
			"phaemosctl config set url https://api.example.org",
			"phaemosctl config set url https://staging.example.org --profile staging",
			"phaemosctl config set default-profile staging",
		},
		args: "<key> <value>", minArgs: 2, maxArgs: 2, allowsNewProfile: true,
		run: runConfigSet,
	})
	register(&command{
		path:    []string{"config", "show"},
		summary: "show the settings in use and where each came from",
		desc: "Shows the config file's path and each profile's address and token (the token's id, name, scope and expiry only, never the " +
			"token itself) and the address and profile this run would use. The order is: a flag, then the environment, then the file.",
		examples: []string{"phaemosctl config show", "phaemosctl config show --output json"},
		run:      runConfigShow,
	})
}

func (r *runCtx) saveConfig() error {
	if r.app.path == "" {
		return usageErr("there is nowhere to keep settings: set PHAEMOS_CONFIG, XDG_CONFIG_HOME or HOME")
	}
	return r.app.cfg.save(r.app.path)
}

func runLogin(r *runCtx) error {
	token, err := r.readToken()
	if err != nil {
		return err
	}
	if !validToken(token) {
		return usageErr("that is not an API token: they start with pht_ and hold no spaces")
	}
	r.client.Token = token
	raw, err := r.client.WhoamiRaw(r.ctx)
	if err != nil {
		return err
	}
	who, err := api.ParseWhoami(raw)
	if err != nil {
		return err
	}
	if who.SignedIn != "token" {
		return newExit(ExitConflict, "the server did not see an API token in that request (it saw a %s)", who.SignedIn)
	}
	prof := r.app.cfg.profile(r.profile)
	if prof.URL == "" || r.app.g.url != "" {
		prof.URL = r.url
	}
	prof.Token = token
	prof.TokenID, prof.TokenName, prof.TokenScope = who.TokenID, singleLine(who.TokenName), who.Scope
	prof.TokenExpires = who.ExpiresAt.Time
	if r.app.cfg.DefaultProfile == "" {
		r.app.cfg.DefaultProfile = r.profile
	}
	if err := r.saveConfig(); err != nil {
		return newExit(ExitFailure, "the token works but could not be stored: %s", err)
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	r.info("Signed in to %s as %s with token %q (scope %s). Stored in %s.", r.url, first(who.Role, "an account"), who.TokenName, first(who.Scope, "unknown"), r.app.path)
	return nil
}

func (r *runCtx) readToken() (string, error) {
	if r.app.io.InTTY {
		if r.app.io.ReadSecret == nil {
			return "", usageErr("there is no way to read the token without echo here: pipe it on standard input")
		}
		return r.app.io.ReadSecret("API token (it will not be shown): ")
	}
	line, err := bufio.NewReader(io.LimitReader(r.app.io.In, 1024)).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return "", usageErr("no token: run this in a terminal to be asked for it or pipe it on standard input")
	}
	return line, nil
}

func runAuthStatus(r *runCtx) error {
	raw, err := r.client.WhoamiRaw(r.ctx)
	if err != nil {
		return err
	}
	who, err := api.ParseWhoami(raw)
	if err != nil {
		return err
	}
	if !who.ExpiresAt.IsZero() {
		left := who.ExpiresAt.Sub(r.app.io.Now())
		if left > 0 && left < expiryWarning {
			r.warn("this token expires in %d days: make a new one on the dashboard before then", int(left.Hours()/24))
		}
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	k := &kv{}
	k.add("server", r.url)
	k.add("profile", r.profile)
	addWho(k, who, r)
	// the token list adds when it was made and last used. It is best effort: nothing depends on it
	if body, err := r.client.TokensRaw(r.ctx); err == nil {
		var tokens []api.TokenInfo
		if json.Unmarshal(body, &tokens) == nil {
			for _, tk := range tokens {
				if tk.ID == who.TokenID {
					k.add("created", timeFmt(tk.CreatedAt, r.loc()))
					if tk.LastUsedAt.IsZero() {
						k.add("last used", "never")
					} else {
						k.add("last used", timeFmt(tk.LastUsedAt, r.loc()))
					}
				}
			}
		}
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

func runLogout(r *runCtx) error {
	prof := r.app.cfg.Profiles[r.profile]
	fromEnv := r.app.io.Getenv("PHAEMOS_TOKEN") != ""
	if prof == nil || prof.Token == "" {
		if fromEnv {
			r.info("No token is stored for profile %q. PHAEMOS_TOKEN is set in the environment: unset it in your shell.", r.profile)
			return nil
		}
		r.info("No token is stored for profile %q.", r.profile)
		return nil
	}
	prof.Token, prof.TokenID, prof.TokenName, prof.TokenScope = "", "", "", ""
	prof.TokenExpires = time.Time{}
	if err := r.saveConfig(); err != nil {
		return err
	}
	r.info("Signed out of profile %q. The token still works until it is revoked on the dashboard or expires.", r.profile)
	if fromEnv {
		r.info("PHAEMOS_TOKEN is still set in the environment: unset it in your shell.")
	}
	return nil
}

func runConfigSet(r *runCtx) error {
	key, value := r.args[0], r.args[1]
	switch key {
	case "url":
		if err := api.CheckURL(value, r.app.g.allowHTTP); err != nil {
			return usageErr("%s", err.Error())
		}
		r.app.cfg.profile(r.profile).URL = strings.TrimRight(value, "/")
	case "default-profile", "profile":
		if !profileName.MatchString(value) {
			return usageErr("%q is not a usable profile name (letters, digits, - and _)", value)
		}
		r.app.cfg.DefaultProfile = value
	case "token":
		return usageErr("a token is never set here, where it would show in your shell history. Use: phaemosctl auth login")
	default:
		return usageErr("unknown setting %q: the settings are url and default-profile", key)
	}
	if err := r.saveConfig(); err != nil {
		return err
	}
	r.info("Saved to %s.", r.app.path)
	return nil
}

func runConfigShow(r *runCtx) error {
	cfg := r.app.cfg
	names := make([]string, 0, len(cfg.Profiles))
	for n := range cfg.Profiles {
		names = append(names, n)
	}
	sort.Strings(names)
	source := func(flagVal, envName, fileVal string) string {
		switch {
		case flagVal != "":
			return "flag"
		case envName != "" && r.app.io.Getenv(envName) != "":
			return "environment"
		case fileVal != "":
			return "config file"
		}
		return "default"
	}
	activeProfile := cfg.Profiles[r.profile]
	fileURL := ""
	if activeProfile != nil {
		fileURL = activeProfile.URL
	}
	profileSource := source(r.app.g.profile, "PHAEMOS_PROFILE", cfg.DefaultProfile)
	urlSource := source(r.app.g.url, "PHAEMOS_URL", fileURL)
	tokenSource := "none"
	switch {
	case r.app.io.Getenv("PHAEMOS_TOKEN") != "":
		tokenSource = "environment"
	case activeProfile != nil && activeProfile.Token != "":
		tokenSource = "config file"
	}
	if r.format != formatTable {
		type tokenView struct {
			ID      string `json:"id,omitempty"`
			Name    string `json:"name,omitempty"`
			Scope   string `json:"scope,omitempty"`
			Expires string `json:"expires,omitempty"`
		}
		type profView struct {
			URL   string     `json:"url,omitempty"`
			Token *tokenView `json:"token"`
		}
		out := map[string]any{
			"config_file": r.app.path, "default_profile": cfg.DefaultProfile,
			"in_use": map[string]string{"profile": r.profile, "profile_source": profileSource, "url": r.url, "url_source": urlSource, "token_source": tokenSource},
		}
		profs := map[string]profView{}
		for _, n := range names {
			p := cfg.Profiles[n]
			v := profView{URL: p.URL}
			if p.Token != "" {
				v.Token = &tokenView{ID: p.TokenID, Name: p.TokenName, Scope: p.TokenScope}
				if !p.TokenExpires.IsZero() {
					v.Token.Expires = isoUTC(p.TokenExpires)
				}
			}
			profs[n] = v
		}
		out["profiles"] = profs
		raw, _ := json.Marshal(out)
		return r.emitRaw(raw)
	}
	k := &kv{}
	k.add("config file", first(r.app.path, "(none)"))
	k.add("default profile", first(cfg.DefaultProfile, "(none)"))
	k.add("in use: profile", fmt.Sprintf("%s (%s)", r.profile, profileSource))
	k.add("in use: address", fmt.Sprintf("%s (%s)", r.url, urlSource))
	k.add("in use: token", tokenSource)
	for _, n := range names {
		p := cfg.Profiles[n]
		k.add("["+n+"] address", first(p.URL, "-"))
		if p.Token == "" {
			k.add("["+n+"] token", "none")
			continue
		}
		text := fmt.Sprintf("%s id %s, scope %s", first(p.TokenName, "(unnamed)"), first(p.TokenID, "?"), first(p.TokenScope, "?"))
		if !p.TokenExpires.IsZero() {
			text += ", expires " + timeFmt(api.Time{Time: p.TokenExpires}, r.loc())
		}
		k.add("["+n+"] token", text)
	}
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}

var _ = flag.ErrHelp
