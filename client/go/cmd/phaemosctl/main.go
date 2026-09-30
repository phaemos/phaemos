// Command phaemosctl checks, feeds and load-tests a PHAEMOS server.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"os"

	"github.com/phaemos/client/go/internal/api"
	"github.com/phaemos/client/go/internal/load"
)

const usage = `phaemosctl checks, feeds and load-tests a PHAEMOS server.

Usage:
  phaemosctl status   [-url URL]
  phaemosctl send     [-url URL] -key KEY -json '{"device_id":"d1","temperature":24.1}'
  phaemosctl load     [-url URL] -key KEY [-requests 500] [-concurrency 20]
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	if err := run(os.Args[1], os.Args[2:]); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run(command string, args []string) error {
	fs := flag.NewFlagSet(command, flag.ExitOnError)
	url := fs.String("url", "http://localhost:8000", "PHAEMOS API base URL")
	key := fs.String("key", os.Getenv("PHAEMOS_API_KEY"), "device API key (or PHAEMOS_API_KEY)")
	body := fs.String("json", "", "reading to send, as JSON")
	requests := fs.Int("requests", 500, "total requests for load")
	concurrency := fs.Int("concurrency", 20, "parallel workers for load")
	if err := fs.Parse(args); err != nil {
		return err
	}
	client := api.New(*url, *key)
	ctx := context.Background()

	switch command {
	case "status":
		status, err := client.Status(ctx)
		if err != nil {
			return err
		}
		return printJSON(status)
	case "send":
		reading := map[string]any{}
		if err := json.Unmarshal([]byte(*body), &reading); err != nil {
			return fmt.Errorf("-json must be a JSON object: %w", err)
		}
		stored, err := client.SendReading(ctx, reading)
		if err != nil {
			return err
		}
		return printJSON(stored)
	case "load":
		if *key == "" {
			return fmt.Errorf("load needs a device key: -key or PHAEMOS_API_KEY")
		}
		result := load.Run(ctx, *requests, *concurrency, func(ctx context.Context, i int) error {
			_, err := client.SendReading(ctx, syntheticReading(i))
			return err
		})
		fmt.Println(result.Summary())
		return nil
	default:
		fmt.Fprint(os.Stderr, usage)
		return fmt.Errorf("unknown command %q", command)
	}
}

func syntheticReading(i int) map[string]any {
	return map[string]any{
		"device_id":   fmt.Sprintf("load-%d", i),
		"node_type":   "esp32",
		"temperature": 24 + rand.Float64(),
		"humidity":    48 + 2*rand.Float64(),
		"vibration_x": 0.05 * rand.Float64(),
		"vibration_y": 0.05 * rand.Float64(),
		"vibration_z": 1.0,
	}
}

func printJSON(v any) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}
