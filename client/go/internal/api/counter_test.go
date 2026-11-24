package api

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestBootRisesAtEveryStartEvenWithTheClockSetBack(t *testing.T) {
	dir := t.TempDir()
	a := NewCounter(dir, "key", time.Unix(1800000000, 0)).Boot()
	b := NewCounter(dir, "key", time.Unix(1800000000, 0)).Boot()
	c := NewCounter(dir, "key", time.Unix(1700000000, 0)).Boot()
	if !(a < b && b < c) {
		t.Fatalf("boots %d %d %d are not rising", a, b, c)
	}
}

func TestBootStartsAboveAnEarlierOneAfterAWipe(t *testing.T) {
	dir := t.TempDir()
	before := NewCounter(dir, "key", time.Unix(1800000000, 0)).Boot()
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		_ = os.Remove(filepath.Join(dir, e.Name()))
	}
	after := NewCounter(dir, "key", time.Unix(1800000100, 0)).Boot()
	if after <= before {
		t.Fatalf("after %d is not above before %d", after, before)
	}
}

func TestBootNeverExceedsTheAPIsLimit(t *testing.T) {
	c := NewCounter(t.TempDir(), "key", time.Unix(9999999999, 0))
	if c.Boot() != MaxBoot {
		t.Fatalf("boot %d", c.Boot())
	}
}

func TestEachKeyHasItsOwnFileAndTheKeyIsNotInTheName(t *testing.T) {
	dir := t.TempDir()
	NewCounter(dir, "secret-key-abc", time.Unix(1800000000, 0))
	NewCounter(dir, "other-key", time.Unix(1800000000, 0))
	entries, _ := os.ReadDir(dir)
	if len(entries) != 2 {
		t.Fatalf("%d files", len(entries))
	}
	for _, e := range entries {
		if filepath.Base(e.Name()) == "boot-secret-key-abc" || len(e.Name()) > 40 {
			t.Fatalf("file name %q", e.Name())
		}
	}
}

func TestStateIsPrivate(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "state")
	NewCounter(dir, "key", time.Unix(1800000000, 0))
	info, err := os.Stat(dir)
	if err != nil || info.Mode().Perm() != 0o700 {
		t.Fatalf("folder mode %v %v", info.Mode().Perm(), err)
	}
	entries, _ := os.ReadDir(dir)
	f, _ := os.Stat(filepath.Join(dir, entries[0].Name()))
	if f.Mode().Perm() != 0o600 {
		t.Fatalf("file mode %v", f.Mode().Perm())
	}
}

func TestAnOpenFolderIsRefusedWithAWarningButBootStillWorks(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0o777); err != nil {
		t.Skip("cannot change the mode here")
	}
	c := NewCounter(dir, "key", time.Unix(1800000000, 0))
	if c.Warning == "" || c.Boot() != 1800000000 {
		t.Fatalf("warning %q boot %d", c.Warning, c.Boot())
	}
}

func TestStampKeepsACallersOwnPair(t *testing.T) {
	c := NewCounter(t.TempDir(), "key", time.Unix(1800000000, 0))
	out, err := c.Stamp(map[string]any{"boot": 5, "seq": 9})
	if err != nil || out["boot"] != 5 || out["seq"] != 9 {
		t.Fatalf("%v %v", out, err)
	}
	if _, ok := out["up"]; ok {
		t.Fatal("up added to a caller's own pair")
	}
}

func TestStampDoesNotChangeTheCallersMap(t *testing.T) {
	c := NewCounter(t.TempDir(), "key", time.Unix(1800000000, 0))
	in := map[string]any{"device_id": "d"}
	if _, err := c.Stamp(in); err != nil || len(in) != 1 {
		t.Fatalf("%v %v", in, err)
	}
}

func TestStateDirOrder(t *testing.T) {
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	if d, _ := StateDir(env(map[string]string{"PHAEMOS_STATE_DIR": "/a", "HOME": "/h"})); d != "/a" {
		t.Fatal(d)
	}
	if d, _ := StateDir(env(map[string]string{"XDG_STATE_HOME": "/x", "HOME": "/h"})); d != "/x/phaemos" {
		t.Fatal(d)
	}
	if d, _ := StateDir(env(map[string]string{"HOME": "/h"})); d != "/h/.local/state/phaemos" {
		t.Fatal(d)
	}
	if _, err := StateDir(env(nil)); err == nil {
		t.Fatal("expected an error")
	}
}
