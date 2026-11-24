package cli

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

// isTerminal asks whether a file is a terminal. The standard library has no call for it and a
// character-device test would call /dev/null a terminal, so stty is asked: it succeeds only on a
// terminal. Where stty is missing the answer is false, which is the safe one (no prompt, no colour).
func isTerminal(f *os.File) bool {
	if f == nil {
		return false
	}
	cmd := exec.Command("stty", "-g")
	cmd.Stdin = f
	return cmd.Run() == nil
}

// readSecretFromTerminal prompts on the terminal and reads a line without echoing it.
func readSecretFromTerminal(prompt string) (string, error) {
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return "", errors.New("there is no terminal to type the token at")
	}
	defer tty.Close()
	fmt.Fprint(tty, prompt)
	off := exec.Command("stty", "-echo")
	off.Stdin = tty
	if err := off.Run(); err != nil {
		return "", errors.New("cannot turn off echo on this terminal, so the token will not be typed here: pipe it on standard input instead")
	}
	restore := func() {
		on := exec.Command("stty", "echo")
		on.Stdin = tty
		_ = on.Run()
		fmt.Fprintln(tty)
	}
	defer restore()
	line, err := bufio.NewReader(tty).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	return strings.TrimSpace(line), nil
}
