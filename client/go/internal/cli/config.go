package cli

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Profile is one named set of settings.
type Profile struct {
	URL          string
	Token        string
	TokenID      string
	TokenName    string
	TokenScope   string
	TokenExpires time.Time
}

// Config is the file. Its format is lines of "key = value" under "[profile]" headings:
//
//	profile = default
//
//	[default]
//	url = https://api.example.org
//	token = pht_...
type Config struct {
	DefaultProfile string
	Profiles       map[string]*Profile
}

var profileName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$`)

func newConfig() *Config { return &Config{Profiles: map[string]*Profile{}} }

// configPath applies the order: $PHAEMOS_CONFIG, then $XDG_CONFIG_HOME/phaemos/config, then
// ~/.config/phaemos/config.
func configPath(getenv func(string) string) (string, error) {
	if p := getenv("PHAEMOS_CONFIG"); p != "" {
		return p, nil
	}
	if x := getenv("XDG_CONFIG_HOME"); x != "" {
		return filepath.Join(x, "phaemos", "config"), nil
	}
	if h := getenv("HOME"); h != "" {
		return filepath.Join(h, ".config", "phaemos", "config"), nil
	}
	return "", errors.New("no config folder: set PHAEMOS_CONFIG, XDG_CONFIG_HOME or HOME")
}

// loadConfig reads the file. A missing file is an empty config. A file that other users can read or
// that is a link or belongs to someone else, is refused, because it can hold a token.
func loadConfig(path string) (*Config, error) {
	cfg := newConfig()
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return nil, fmt.Errorf("cannot read the config file %s: %w", path, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("the config file %s is a link or not a regular file", path)
	}
	if permissionBitsApply {
		if mode := info.Mode().Perm(); mode&0o077 != 0 {
			return nil, fmt.Errorf("the config file %s has mode %03o: other users can read it. Run: chmod 600 %s", path, mode, path)
		}
		if !ownedByMe(info) {
			return nil, fmt.Errorf("the config file %s belongs to another user", path)
		}
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("cannot read the config file %s: %w", path, err)
	}
	defer f.Close()
	if err := parseConfig(f, cfg); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return cfg, nil
}

func parseConfig(r io.Reader, cfg *Config) error {
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 4096), 64*1024)
	var current *Profile
	n := 0
	for scanner.Scan() {
		n++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") {
			if !strings.HasSuffix(line, "]") {
				return fmt.Errorf("line %d: a section heading must look like [name]", n)
			}
			name := strings.TrimSpace(line[1 : len(line)-1])
			if !profileName.MatchString(name) {
				return fmt.Errorf("line %d: %q is not a usable profile name", n, name)
			}
			current = cfg.Profiles[name]
			if current == nil {
				current = &Profile{}
				cfg.Profiles[name] = current
			}
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return fmt.Errorf("line %d: expected key = value", n)
		}
		key, value = strings.TrimSpace(key), strings.TrimSpace(value)
		if current == nil {
			if key != "profile" {
				return fmt.Errorf("line %d: %q belongs under a [profile] heading", n, key)
			}
			cfg.DefaultProfile = value
			continue
		}
		switch key {
		case "url":
			current.URL = value
		case "token":
			current.Token = value
		case "token_id":
			current.TokenID = value
		case "token_name":
			current.TokenName = value
		case "token_scope":
			current.TokenScope = value
		case "token_expires":
			t, err := time.Parse(time.RFC3339, value)
			if err != nil {
				return fmt.Errorf("line %d: token_expires must be an RFC 3339 time", n)
			}
			current.TokenExpires = t
		default:
			return fmt.Errorf("line %d: unknown key %q", n, key)
		}
	}
	return scanner.Err()
}

func (c *Config) render() []byte {
	var b strings.Builder
	b.WriteString("# phaemosctl settings. This file can hold API tokens: keep it mode 0600.\n")
	if c.DefaultProfile != "" {
		fmt.Fprintf(&b, "profile = %s\n", c.DefaultProfile)
	}
	names := make([]string, 0, len(c.Profiles))
	for name := range c.Profiles {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		p := c.Profiles[name]
		fmt.Fprintf(&b, "\n[%s]\n", name)
		if p.URL != "" {
			fmt.Fprintf(&b, "url = %s\n", p.URL)
		}
		if p.Token != "" {
			fmt.Fprintf(&b, "token = %s\n", p.Token)
			if p.TokenID != "" {
				fmt.Fprintf(&b, "token_id = %s\n", p.TokenID)
			}
			if p.TokenName != "" {
				fmt.Fprintf(&b, "token_name = %s\n", singleLine(p.TokenName))
			}
			if p.TokenScope != "" {
				fmt.Fprintf(&b, "token_scope = %s\n", p.TokenScope)
			}
			if !p.TokenExpires.IsZero() {
				fmt.Fprintf(&b, "token_expires = %s\n", p.TokenExpires.UTC().Format(time.RFC3339))
			}
		}
	}
	return []byte(b.String())
}

func singleLine(s string) string { return strings.NewReplacer("\n", " ", "\r", " ").Replace(s) }

// save writes the file atomically with mode 0600 in a folder of mode 0700.
func (c *Config) save(path string) error {
	dir := filepath.Dir(path)
	if _, err := os.Stat(dir); errors.Is(err, os.ErrNotExist) {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return fmt.Errorf("cannot create %s: %w", dir, err)
		}
	}
	info, err := os.Stat(dir)
	if err != nil {
		return err
	}
	if permissionBitsApply && info.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("the folder %s can be written by other users, so a token kept there could be swapped: run chmod go-w on it", dir)
	}
	temp := path + ".tmp"
	_ = os.Remove(temp)
	f, err := os.OpenFile(temp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(c.render()); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(temp, path)
}

func (c *Config) profile(name string) *Profile {
	p := c.Profiles[name]
	if p == nil {
		p = &Profile{}
		c.Profiles[name] = p
	}
	return p
}

// validToken says whether text looks like an API token. It never echoes the text.
func validToken(text string) bool {
	if !strings.HasPrefix(text, "pht_") || len(text) < 12 || len(text) > 512 {
		return false
	}
	for _, r := range text {
		if r <= ' ' || r >= 0x7f {
			return false
		}
	}
	return true
}
