// Command phaemosctl is the command line tool for a PHAEMOS server.
package main

import (
	"context"
	"os"
	"os/signal"

	"github.com/phaemos/client/go/internal/cli"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	code := cli.Run(ctx, os.Args[1:], cli.RealIO())
	stop()
	os.Exit(code)
}
