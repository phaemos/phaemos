package cli

import (
	"flag"
	"fmt"
	"io"
	"sort"
	"strings"
	"time"
)

// command is one entry in the tool. The same record drives the help, the completion scripts and the
// dispatch, so they cannot disagree.
type command struct {
	path     []string
	summary  string
	desc     string
	examples []string
	args     string
	minArgs  int
	maxArgs  int
	flags    func(fs *flag.FlagSet)
	run      func(*runCtx) error
	// needsToken makes a missing token exit 3 before anything is sent.
	needsToken bool
	// timeout is the default total time. Zero means 60 seconds. Negative means no limit.
	timeout time.Duration
	// scope is the least token scope the command needs (read when empty).
	scope string
	// noConfig skips loading the config and resolving the profile.
	noConfig bool
	// allowsNewProfile lets a command name a profile that does not exist yet.
	allowsNewProfile bool
	// followsUntilCancelled makes an interrupt a clean end.
	followsUntilCancelled bool
}

var commands []*command

// aliases are names kept so that scripts written earlier keep working. They are not listed in the help.
var aliases = map[string]string{"machines": "devices", "send": "dev send", "load": "dev load"}

func register(c *command) { commands = append(commands, c) }

func (c *command) name() string { return strings.Join(c.path, " ") }

func nouns() map[string][]*command {
	m := map[string][]*command{}
	for _, c := range commands {
		if len(c.path) == 2 {
			m[c.path[0]] = append(m[c.path[0]], c)
		}
	}
	return m
}

// find returns the command for the arguments and the arguments left over. A nil command with no error
// means help was asked for.
func (a *app) find(args []string) (*command, []string, error) {
	first := args[0]
	// the old names still work: machines is devices and send and load moved under dev
	if to, ok := aliases[first]; ok {
		args = append(strings.Fields(to), args[1:]...)
		first = args[0]
	}
	if first == "help" {
		return nil, args[1:], nil
	}
	if first == "-h" || first == "--help" {
		return nil, nil, nil
	}
	for _, c := range commands {
		if len(c.path) == 1 && c.path[0] == first {
			return c, args[1:], nil
		}
	}
	verbs, isNoun := nouns()[first]
	if isNoun {
		if len(args) < 2 || strings.HasPrefix(args[1], "-") {
			names := make([]string, 0, len(verbs))
			for _, v := range verbs {
				names = append(names, v.path[1])
			}
			sort.Strings(names)
			return nil, nil, usageErr("%s needs a verb: %s. Try: phaemosctl help %s", first, strings.Join(names, ", "), first)
		}
		for _, c := range verbs {
			if c.path[1] == args[1] {
				return c, args[2:], nil
			}
		}
		if first == "alerts" && (args[1] == "ack" || args[1] == "acknowledge") {
			return nil, nil, usageErr("the API has no acknowledge step for alerts, only resolve: try phaemosctl alerts resolve <id>")
		}
		return nil, nil, usageErr("unknown command %q.%s", first+" "+args[1], suggest(first+" "+args[1]))
	}
	return nil, nil, usageErr("unknown command %q.%s", first, suggest(first))
}

func allNames() []string {
	set := map[string]bool{}
	for _, c := range commands {
		set[c.name()] = true
		set[c.path[0]] = true
	}
	names := make([]string, 0, len(set))
	for n := range set {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

func suggest(typed string) string {
	best, bestDist := "", 1<<30
	candidates := map[string]string{}
	for _, name := range allNames() {
		candidates[name] = name
	}
	// an old name that is close is answered with the name that replaced it
	for old, now := range aliases {
		candidates[old] = now
	}
	for name, shown := range candidates {
		if d := levenshtein(typed, name); d < bestDist || (d == bestDist && shown < best) {
			best, bestDist = shown, d
		}
	}
	limit := 3
	if len(typed) <= 4 {
		limit = 2
	}
	if bestDist <= limit {
		return fmt.Sprintf(" Did you mean: phaemosctl %s", best)
	}
	return " See: phaemosctl help"
}

func levenshtein(a, b string) int {
	ra, rb := []rune(a), []rune(b)
	prev := make([]int, len(rb)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(ra); i++ {
		cur := make([]int, len(rb)+1)
		cur[0] = i
		for j := 1; j <= len(rb); j++ {
			cost := 1
			if ra[i-1] == rb[j-1] {
				cost = 0
			}
			cur[j] = min(prev[j]+1, cur[j-1]+1, prev[j-1]+cost)
		}
		prev = cur
	}
	return prev[len(rb)]
}

func (a *app) help(tail []string) int {
	if len(tail) == 0 {
		a.helpTop(a.io.Out)
		return ExitOK
	}
	// help <command>
	cmd, _, err := a.find(tail)
	if err != nil {
		// a noun alone lists its verbs
		if verbs, ok := nouns()[tail[0]]; ok && len(tail) == 1 {
			a.helpNoun(a.io.Out, tail[0], verbs)
			return ExitOK
		}
		return a.fail(err)
	}
	if cmd == nil {
		a.helpTop(a.io.Out)
		return ExitOK
	}
	a.printHelp(a.io.Out, cmd)
	return ExitOK
}

func (a *app) helpNoun(w io.Writer, noun string, verbs []*command) {
	fmt.Fprintf(w, "phaemosctl %s: %s\n\nCommands:\n", noun, nounSummary[noun])
	sort.Slice(verbs, func(i, j int) bool { return verbs[i].path[1] < verbs[j].path[1] })
	for _, v := range verbs {
		fmt.Fprintf(w, "  %-22s %s\n", v.name(), v.summary)
	}
	fmt.Fprintf(w, "\nSee: phaemosctl help %s <verb>\n", noun)
}

var nounSummary = map[string]string{
	"dev":      "commands that act as a device, with a device key",
	"devices":  "the devices you may read and the one recovery a token may do",
	"tokens":   "your API tokens",
	"windows":  "maintenance windows that silence alerts",
	"auth":     "sign in, check and sign out",
	"config":   "view and change settings",
	"readings": "a machine's sensor readings",
	"alerts":   "alerts raised on machines",
	"tickets":  "maintenance tickets",
	"model":    "the anomaly model",
}

func (a *app) helpTop(w io.Writer) {
	fmt.Fprint(w, "phaemosctl: the command line tool for a PHAEMOS server\n\nUsage:\n  phaemosctl [options] <command> [arguments]\n\nCommands:\n")
	for _, c := range a.sortedCommands() {
		fmt.Fprintf(w, "  %-22s %s\n", c.name(), c.summary)
	}
	fmt.Fprint(w, `
Run phaemosctl help <command> for the options and examples of one command.

Settings are taken from a flag first, then the environment, then the config file.
The token never comes from a flag: use phaemosctl auth login or PHAEMOS_TOKEN.

Exit codes:
`)
	fmt.Fprint(w, exitCodeTable)
}

const exitCodeTable = `  0  success
  1  a general failure
  2  a usage error
  3  not signed in or the token was refused
  4  not allowed
  5  not found
  6  a conflict or the server refused the request as invalid
  7  rate limited, after retries
  8  the server or the network failed
`

func (a *app) printHelp(w io.Writer, c *command) {
	fs := flag.NewFlagSet(c.name(), flag.ContinueOnError)
	(&globals{timeout: -1}).register(fs)
	if c.flags != nil {
		c.flags(fs)
	}
	fmt.Fprintf(w, "phaemosctl %s: %s\n\nUsage:\n  phaemosctl %s", c.name(), c.summary, c.name())
	if c.args != "" {
		fmt.Fprintf(w, " %s", c.args)
	}
	fmt.Fprint(w, " [options]\n\n")
	fmt.Fprintf(w, "%s\n\nExamples:\n", wrap(c.desc, 78))
	for _, ex := range c.examples {
		fmt.Fprintf(w, "  $ %s\n", ex)
	}
	own, shared := map[string]bool{}, map[string]bool{}
	g := flag.NewFlagSet("g", flag.ContinueOnError)
	(&globals{}).register(g)
	g.VisitAll(func(f *flag.Flag) { shared[f.Name] = true })
	fs.VisitAll(func(f *flag.Flag) {
		if !shared[f.Name] {
			own[f.Name] = true
		}
	})
	if len(own) > 0 {
		fmt.Fprint(w, "\nOptions:\n")
		fs.VisitAll(func(f *flag.Flag) {
			if own[f.Name] {
				writeFlag(w, f)
			}
		})
	}
	fmt.Fprint(w, "\nOptions for every command:\n")
	fs.VisitAll(func(f *flag.Flag) {
		if shared[f.Name] && f.Name != "o" {
			writeFlag(w, f)
		}
	})
	fmt.Fprint(w, "\nExit codes: 0 success, 1 failure, 2 usage, 3 not signed in, 4 not allowed, 5 not found, 6 conflict or invalid, 7 rate limited, 8 server or network.\n")
}

func writeFlag(w io.Writer, f *flag.Flag) {
	kind := ""
	switch f.Value.(flag.Getter).Get().(type) {
	case string:
		kind = " <text>"
	case int:
		kind = " <number>"
	case time.Duration:
		kind = " <duration>"
	}
	def := ""
	if f.DefValue != "" && f.DefValue != "false" && f.DefValue != "0" && f.DefValue != "0s" && f.DefValue != "-1ns" {
		def = fmt.Sprintf(" (default %s)", f.DefValue)
	}
	fmt.Fprintf(w, "  --%s%s\n      %s%s\n", f.Name, kind, f.Usage, def)
}

func wrap(text string, width int) string {
	var out []string
	for _, para := range strings.Split(text, "\n") {
		line := ""
		for _, word := range strings.Fields(para) {
			if line != "" && len(line)+1+len(word) > width {
				out = append(out, line)
				line = word
			} else if line == "" {
				line = word
			} else {
				line += " " + word
			}
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}
