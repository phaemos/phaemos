package api

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// MaxBoot and MaxSeq are the largest values the API accepts for boot and seq.
const (
	MaxBoot = 2147483647
	MaxSeq  = 4294967295
)

// Counter stamps readings with boot, seq and up, so the machine behind the key is protected from
// replays. The API refuses a post whose (boot, seq) is not newer than the last it accepted.
//
// boot is kept in a small file in the state folder (mode 0600 in a folder of mode 0700), one file
// per key (named by a hash of the key, never the key itself). At each start it becomes the larger of
// the stored value plus one and the Unix time in seconds, so it still rises if the file was wiped.
// seq starts at 0 for each run. Two programs started in the same second with the same key can get the
// same boot: run one at a time per key.
type Counter struct {
	mu    sync.Mutex
	boot  uint64
	seq   uint64
	start time.Time
	// Warning is set when the boot counter could not be stored. The boot is still usable for this
	// run, but a later run could repeat it if the clock were set back.
	Warning string
}

// StateDir returns the folder for the counter file: PHAEMOS_STATE_DIR, else XDG_STATE_HOME/phaemos,
// else $HOME/.local/state/phaemos.
func StateDir(getenv func(string) string) (string, error) {
	if dir := getenv("PHAEMOS_STATE_DIR"); dir != "" {
		return dir, nil
	}
	if dir := getenv("XDG_STATE_HOME"); dir != "" {
		return filepath.Join(dir, "phaemos"), nil
	}
	if home := getenv("HOME"); home != "" {
		return filepath.Join(home, ".local", "state", "phaemos"), nil
	}
	return "", errors.New("no state folder: set PHAEMOS_STATE_DIR or HOME")
}

// NewCounter starts a new boot for the key. It never fails outright: when the counter cannot be
// stored it returns a working counter with Warning set.
func NewCounter(stateDir, key string, now time.Time) *Counter {
	c := &Counter{start: now}
	fromClock := uint64(now.Unix())
	if now.Unix() < 0 {
		fromClock = 0
	}
	if fromClock > MaxBoot {
		fromClock = MaxBoot
	}
	c.boot = fromClock
	sum := sha256.Sum256([]byte(key))
	path := filepath.Join(stateDir, "boot-"+hex.EncodeToString(sum[:8]))
	previous, err := readCounter(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		c.Warning = "the boot counter file is unreadable, so boot comes from the clock only: " + err.Error()
	}
	if previous+1 > c.boot {
		c.boot = previous + 1
	}
	if c.boot > MaxBoot {
		c.boot = MaxBoot
		c.Warning = "the boot counter has reached the API's limit"
	}
	if err := storeCounter(stateDir, path, c.boot); err != nil && c.Warning == "" {
		c.Warning = "the boot counter could not be stored (" + err.Error() + "): a later run may repeat a boot"
	}
	return c
}

func readCounter(path string) (uint64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	return strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
}

func storeCounter(dir, path string, boot uint64) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return fmt.Errorf("%s is not a plain folder", dir)
	}
	if info.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("%s can be written by other users", dir)
	}
	temp := path + ".tmp"
	_ = os.Remove(temp)
	file, err := os.OpenFile(temp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(file, "%d\n", boot); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	return os.Rename(temp, path)
}

// Boot returns this run's boot number.
func (c *Counter) Boot() uint64 { return c.boot }

// Stamp returns a copy of the reading with boot, seq and up added. A reading that already carries
// boot or seq is returned as it is: the caller chose them.
func (c *Counter) Stamp(reading map[string]any) (map[string]any, error) {
	out := make(map[string]any, len(reading)+3)
	for k, v := range reading {
		out[k] = v
	}
	if _, ok := out["boot"]; ok {
		return out, nil
	}
	if _, ok := out["seq"]; ok {
		return out, nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.seq > MaxSeq {
		return nil, errors.New("the sequence number is used up for this run")
	}
	out["boot"] = c.boot
	out["seq"] = c.seq
	out["up"] = int64(time.Since(c.start).Seconds())
	c.seq++
	return out, nil
}
