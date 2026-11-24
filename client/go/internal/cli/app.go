// Package cli is the phaemosctl command line tool. Run is its only entry point, so everything the
// tool does can be driven from a test with a fake terminal and a fake server.
package cli

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/phaemos/client/go/internal/api"
)

// Version is set at build time: go build -ldflags "-X github.com/phaemos/client/go/internal/cli.Version=1.2.3".
var (
	Version = "dev"
	Commit  = ""
)

// IO is everything the tool touches outside itself.
type IO struct {
	In     io.Reader
	Out    io.Writer
	Err    io.Writer
	InTTY  bool
	OutTTY bool
	Getenv func(string) string
	// ReadSecret prompts and reads a line without echo. Nil when there is no terminal.
	ReadSecret func(prompt string) (string, error)
	Clock      api.Clock
	Now        func() time.Time
	Loc        *time.Location
	HTTP       *http.Client
	Version    string
	// Rand is the source of random bytes (for idempotency keys). Nil means crypto/rand.
	Rand io.Reader
}

// RealIO builds the IO of a normal run.
func RealIO() IO {
	io := IO{
		In: os.Stdin, Out: os.Stdout, Err: os.Stderr,
		InTTY: isTerminal(os.Stdin), OutTTY: isTerminal(os.Stdout),
		Getenv: os.Getenv, Now: time.Now, Loc: time.Local, Version: Version, Clock: api.SystemClock(),
	}
	if io.InTTY {
		io.ReadSecret = readSecretFromTerminal
	}
	return io
}

type globals struct {
	profile   string
	url       string
	output    string
	noColor   bool
	quiet     bool
	verbose   bool
	allowHTTP bool
	timeout   time.Duration
}

func (g *globals) register(fs *flag.FlagSet) {
	fs.StringVar(&g.profile, "profile", g.profile, "settings profile to use (default: the file's default profile)")
	fs.StringVar(&g.url, "url", g.url, "API address (default: PHAEMOS_URL, then the profile)")
	fs.StringVar(&g.output, "output", g.output, "output format: table, json or jsonl")
	fs.StringVar(&g.output, "o", g.output, "short for --output")
	fs.BoolVar(&g.noColor, "no-color", g.noColor, "never use colour (NO_COLOR does the same)")
	fs.BoolVar(&g.quiet, "quiet", g.quiet, "print only the result and errors")
	fs.BoolVar(&g.verbose, "verbose", g.verbose, "show each request's method, path, status and time on standard error")
	fs.BoolVar(&g.allowHTTP, "allow-insecure-http", g.allowHTTP, "allow plain http:// to a host that is not local (bench testing only)")
	fs.DurationVar(&g.timeout, "timeout", g.timeout, "total time allowed for the command (default 60s, 10m for an export, none for tail, 0 for no limit)")
}

// app is one run.
type app struct {
	io   IO
	g    *globals
	cfg  *Config
	path string
}

// runCtx is what a command handler gets.
type runCtx struct {
	app    *app
	ctx    context.Context
	cmd    *command
	fs     *flag.FlagSet
	args   []string
	format outputFormat
	client *api.Client
	// profile is the resolved profile name and settings, with the token that will be used.
	profile string
	url     string
	// slashStripped says the configured address ended in a slash that was removed.
	slashStripped bool
	token         string
}

func (r *runCtx) out() io.Writer  { return r.app.io.Out }
func (r *runCtx) errw() io.Writer { return r.app.io.Err }

func (r *runCtx) painter() painter {
	g := r.app.g
	on := r.app.io.OutTTY && !g.noColor && r.app.io.Getenv("NO_COLOR") == "" && r.app.io.Getenv("TERM") != "dumb"
	return painter{on: on}
}

func (r *runCtx) warn(format string, args ...any) {
	if !r.app.g.quiet {
		fmt.Fprintf(r.errw(), "warning: "+format+"\n", args...)
	}
}

func (r *runCtx) info(format string, args ...any) {
	if !r.app.g.quiet {
		fmt.Fprintf(r.errw(), format+"\n", args...)
	}
}

func (r *runCtx) loc() *time.Location {
	if r.app.io.Loc != nil {
		return r.app.io.Loc
	}
	return time.Local
}

func (r *runCtx) str(name string) string {
	return r.fs.Lookup(name).Value.(flag.Getter).Get().(string)
}
func (r *runCtx) integer(name string) int  { return r.fs.Lookup(name).Value.(flag.Getter).Get().(int) }
func (r *runCtx) boolean(name string) bool { return r.fs.Lookup(name).Value.(flag.Getter).Get().(bool) }
func (r *runCtx) duration(name string) time.Duration {
	return r.fs.Lookup(name).Value.(flag.Getter).Get().(time.Duration)
}

type scrubWriter struct{ w io.Writer }

var tokenText = regexp.MustCompile(`pht_[A-Za-z0-9_\-]+`)

func (s scrubWriter) Write(p []byte) (int, error) {
	if !bytes.Contains(p, []byte("pht_")) {
		return s.w.Write(p)
	}
	if _, err := s.w.Write(tokenText.ReplaceAll(p, []byte("<token>"))); err != nil {
		return 0, err
	}
	return len(p), nil
}

// Run runs the tool and returns its exit code.
func Run(ctx context.Context, args []string, io IO) int {
	// whatever is written, on either stream, has anything shaped like an API token blanked. A server
	// that echoed a token in a reply would otherwise put it on the screen
	io.Out, io.Err = scrubWriter{io.Out}, scrubWriter{io.Err}
	a := &app{io: io, g: &globals{timeout: -1}}
	return a.run(ctx, args)
}

func (a *app) fail(err error) int {
	ee := classify(err)
	if ee.silent {
		return ee.Code
	}
	format, _ := parseFormat(a.g.output)
	if format == formatJSON || format == formatJSONL {
		fmt.Fprintf(a.io.Err, "%s\n", ee.json())
	} else {
		fmt.Fprintf(a.io.Err, "error: %s\n", ee.Message)
	}
	return ee.Code
}

func (a *app) run(ctx context.Context, args []string) int {
	if len(args) > 0 && (args[0] == "--version" || args[0] == "-version") {
		args = append([]string{"version"}, args[1:]...)
	}
	// global flags before the command
	pre := flag.NewFlagSet("phaemosctl", flag.ContinueOnError)
	pre.SetOutput(io.Discard)
	a.g.register(pre)
	pre.Usage = func() {}
	rest := args
	for {
		if err := pre.Parse(rest); err != nil {
			if err == flag.ErrHelp {
				a.helpTop(a.io.Out)
				return ExitOK
			}
			return a.fail(usageErr("%s. Try: phaemosctl help", strings.TrimPrefix(err.Error(), "flag provided but not defined: ")))
		}
		rest = pre.Args()
		break
	}
	if len(rest) == 0 {
		a.helpTop(a.io.Err)
		return ExitUsage
	}

	if rest[0] == "--version" || rest[0] == "-version" {
		rest = []string{"version"}
	}
	cmd, tail, err := a.find(rest)
	if err != nil {
		return a.fail(err)
	}
	if cmd == nil { // help
		return a.help(tail)
	}

	fs := flag.NewFlagSet(strings.Join(cmd.path, " "), flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	a.g.register(fs)
	if cmd.flags != nil {
		cmd.flags(fs)
	}
	positionals, err := parseInterspersed(fs, tail)
	if err != nil {
		if err == flag.ErrHelp {
			a.printHelp(a.io.Out, cmd)
			return ExitOK
		}
		return a.fail(usageErr("%s. See: phaemosctl help %s", cleanFlagError(err), strings.Join(cmd.path, " ")))
	}
	format, err := parseFormat(a.g.output)
	if err != nil {
		return a.fail(err)
	}
	if len(positionals) < cmd.minArgs || len(positionals) > cmd.maxArgs {
		return a.fail(usageErr("usage: phaemosctl %s %s", strings.Join(cmd.path, " "), cmd.args))
	}

	if cmd.noConfig {
		// nothing to load
	} else if err := a.loadConfig(); err != nil {
		return a.fail(usageErr("%s", err.Error()))
	}

	timeout := a.g.timeout
	if timeout < 0 {
		timeout = cmd.timeout
		if timeout == 0 {
			timeout = 60 * time.Second
		}
	}
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	rc := &runCtx{app: a, ctx: ctx, cmd: cmd, fs: fs, args: positionals, format: format}
	if !cmd.noConfig {
		if err := a.resolve(rc); err != nil {
			return a.fail(err)
		}
	}
	if cmd.needsToken {
		if err := rc.needToken(); err != nil {
			return a.fail(err)
		}
	}
	if err := cmd.run(rc); err != nil {
		if ctx.Err() == context.Canceled && cmd.followsUntilCancelled {
			return ExitOK
		}
		ee := classify(err)
		if ee.Code == ExitForbidden && cmd.needsToken && strings.Contains(strings.ToLower(ee.Message), "scope") {
			need := first(cmd.scope, "read")
			have := ""
			if p := a.profileOf(rc.profile); p != nil && p.TokenScope != "" && a.io.Getenv("PHAEMOS_TOKEN") == "" {
				have = fmt.Sprintf(" and this token has the %s scope", p.TokenScope)
			}
			ee = &exitError{Code: ee.Code, Kind: ee.Kind, Status: ee.Status, Message: ee.Message + fmt.Sprintf(" (this command needs the %s scope%s)", need, have)}
		}
		return a.fail(ee)
	}
	return ExitOK
}

func (a *app) profileOf(name string) *Profile {
	if a.cfg == nil {
		return nil
	}
	return a.cfg.Profiles[name]
}

func cleanFlagError(err error) string {
	s := err.Error()
	s = strings.Replace(s, "flag provided but not defined: -", "unknown option --", 1)
	return s
}

// parseInterspersed lets options come before, between or after the positional arguments.
func parseInterspersed(fs *flag.FlagSet, args []string) ([]string, error) {
	var positionals []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		args = fs.Args()
		if len(args) == 0 {
			return positionals, nil
		}
		if args[0] == "--" {
			return append(positionals, args[1:]...), nil
		}
		positionals = append(positionals, args[0])
		args = args[1:]
	}
}

func (a *app) loadConfig() error {
	path, err := configPath(a.io.Getenv)
	if err != nil {
		// no place for a file: run with the environment and flags alone
		a.cfg = newConfig()
		return nil
	}
	a.path = path
	cfg, err := loadConfig(path)
	if err != nil {
		return err
	}
	a.cfg = cfg
	return nil
}

// resolve applies the precedence: a flag, then the environment, then the config file, then the default.
func (a *app) resolve(rc *runCtx) error {
	g := a.g
	env := a.io.Getenv
	name := first(g.profile, env("PHAEMOS_PROFILE"), a.cfg.DefaultProfile, "default")
	prof := a.cfg.Profiles[name]
	explicit := first(g.profile, env("PHAEMOS_PROFILE")) != ""
	if prof == nil {
		if explicit && g.url == "" && env("PHAEMOS_URL") == "" && !rc.cmd.allowsNewProfile {
			return usageErr("there is no profile called %q. Make it with: phaemosctl config set url <address> --profile %s", name, name)
		}
		prof = &Profile{}
	}
	rc.profile = name
	raw := first(g.url, env("PHAEMOS_URL"), prof.URL, "http://localhost:8000")
	// the server answers 404 for a path with a trailing slash, so trailing slashes are always stripped
	rc.url = api.NormaliseURL(raw)
	rc.slashStripped = strings.TrimSpace(raw) != rc.url
	rc.token = first(env("PHAEMOS_TOKEN"), prof.Token)
	if rc.token != "" && !validToken(rc.token) {
		return usageErr("the token (from PHAEMOS_TOKEN or the config file) is not an API token: they start with pht_")
	}
	if err := api.CheckURL(rc.url, g.allowHTTP); err != nil {
		return usageErr("%s", err.Error())
	}
	if g.allowHTTP && strings.HasPrefix(rc.url, "http://") && !hostIsLocal(rc.url) {
		rc.warn("plain HTTP to a non-local host: the token and the readings are not encrypted")
	}
	client := api.New(rc.url, "")
	client.Token = rc.token
	client.Retry = api.DefaultRetry
	client.Clock = a.io.Clock
	client.MaxReply = 4 << 20
	client.UserAgent = "phaemosctl/" + Version
	if a.io.HTTP != nil {
		client.HTTP = a.io.HTTP
	}
	if g.verbose {
		seen := map[string]bool{}
		client.OnDeprecated = func(method, path, sunset string) {
			if seen[method+path] {
				return
			}
			seen[method+path] = true
			text := fmt.Sprintf("notice: %s %s is deprecated and will be removed", method, path)
			if sunset != "" {
				text += " after " + sunset
			}
			fmt.Fprintln(a.io.Err, text+": update phaemosctl")
		}
		client.Trace = func(method, path string, status int, took time.Duration) {
			if status == 0 {
				fmt.Fprintf(a.io.Err, "%s %s -> no reply (%dms)\n", method, path, took.Milliseconds())
				return
			}
			fmt.Fprintf(a.io.Err, "%s %s -> %d (%dms)\n", method, path, status, took.Milliseconds())
		}
	}
	rc.client = client
	if rc.token != "" && prof.Token == rc.token && !prof.TokenExpires.IsZero() {
		left := prof.TokenExpires.Sub(a.io.Now())
		if left < expiryWarning && left > 0 {
			rc.warn("this token expires in %d days: make a new one before then", int(left.Hours()/24))
		} else if left <= 0 {
			rc.warn("this token has expired: sign in again with: phaemosctl auth login")
		}
	}
	return nil
}

const expiryWarning = 14 * 24 * time.Hour

func first(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

func hostIsLocal(raw string) bool {
	rest := strings.TrimPrefix(strings.TrimPrefix(raw, "http://"), "https://")
	host := strings.Split(rest, "/")[0]
	if i := strings.LastIndex(host, ":"); i > 0 && !strings.HasSuffix(host, "]") {
		host = host[:i]
	}
	return api.IsLocalHost(strings.Trim(host, "[]"))
}

// needToken returns the error for a command that needs a token and has none.
func (r *runCtx) needToken() error {
	if r.token == "" {
		return newExit(ExitNotSignedIn, "not signed in: run phaemosctl auth login or set PHAEMOS_TOKEN")
	}
	return nil
}

func (a *app) sortedCommands() []*command {
	list := append([]*command(nil), commands...)
	sort.Slice(list, func(i, j int) bool { return strings.Join(list[i].path, " ") < strings.Join(list[j].path, " ") })
	return list
}

// idempotencyKey makes a random key for one command run (32 visible characters).
func (a *app) idempotencyKey() (string, error) {
	var source io.Reader = rand.Reader
	if a.io.Rand != nil {
		source = a.io.Rand
	}
	b := make([]byte, 16)
	if _, err := io.ReadFull(source, b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}
