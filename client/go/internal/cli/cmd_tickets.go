package cli

import (
	"encoding/json"
	"flag"
	"fmt"
	"strconv"
	"strings"

	"github.com/phaemos/client/go/internal/api"
)

func init() {
	register(&command{
		path:     []string{"tickets", "list"},
		summary:  "list maintenance tickets, newest first",
		desc:     "Lists tickets you may read. --status, --priority, --alert and --machine (a device, by id or name) are the server's own filters.",
		examples: []string{"phaemosctl tickets list --status open", "phaemosctl tickets list --machine press-01 --priority high --output json"},
		flags: func(fs *flag.FlagSet) {
			limitFlag(fs)
			fs.String("status", "", "open, in_progress or closed")
			fs.String("priority", "", "low, medium, high or critical")
			fs.String("alert", "", "only tickets raised from this alert id")
			fs.String("machine", "", "only this machine (id or name)")
			fs.Bool("wide", false, "also show the ticket id")
		},
		needsToken: true,
		run:        runTicketsList,
	})
	register(&command{
		path:     []string{"tickets", "show"},
		summary:  "show one ticket in full",
		desc:     "Shows a ticket by id or by number (PHM-0001 or 1). A number is looked up with the server's ticket_number filter.",
		examples: []string{"phaemosctl tickets show PHM-0012", "phaemosctl tickets show 0b6c1f0e-1111-4222-8333-444455556666 --output json"},
		args:     "<id or number>", minArgs: 1, maxArgs: 1, needsToken: true,
		run: runTicketsShow,
	})
}

func ticketNumber(n *int) string {
	if n == nil {
		return "-"
	}
	return fmt.Sprintf("PHM-%04d", *n)
}

func runTicketsList(r *runCtx) error {
	limit, err := r.limit()
	if err != nil {
		return err
	}
	machineID := ""
	if m := r.str("machine"); m != "" {
		dev, err := r.machineID(m)
		if err != nil {
			return err
		}
		machineID = dev.ID
	}
	res, err := r.client.ListTicketsFor(r.ctx, api.TicketFilter{Status: r.str("status"), Priority: r.str("priority"), AlertID: r.str("alert"), DeviceID: machineID}, limit)
	if err != nil {
		return err
	}
	tickets, err := api.DecodeAll[api.Ticket](res.Items)
	if err != nil {
		return err
	}
	keepItems, kept := res.Items, tickets
	r.warnMore(res, "tickets")
	if r.format != formatTable {
		return writeList(r.out(), keepItems, r.format)
	}
	t := &table{Headers: []string{"NUMBER", "STATUS", "PRIORITY", "TITLE", "ASSIGNED", "UPDATED"}}
	if r.boolean("wide") {
		t.Headers = append(t.Headers, "ID")
	}
	for _, tk := range kept {
		style := ""
		if tk.Status == "open" {
			style = "yellow"
		}
		row := []cell{plain(ticketNumber(tk.TicketNumber)), {Text: tk.Status, Style: style}, {Text: first(strPtr(tk.Priority), "-"), Style: sevStyle(strPtr(tk.Priority))},
			plain(clip(first(strPtr(tk.Title), "-"), 60)), plain(str(tk.AssignedToName)), plain(timeFmt(tk.UpdatedAt, r.loc()))}
		if r.boolean("wide") {
			row = append(row, plain(tk.ID))
		}
		t.add(row...)
	}
	renderTable(r.out(), t, r.app.io.OutTTY, r.painter())
	return nil
}

func runTicketsShow(r *runCtx) error {
	ref := r.args[0]
	var raw []byte
	if api.IsUUID(ref) {
		var err error
		if raw, err = r.client.GetTicketRaw(r.ctx, ref); err != nil {
			return err
		}
	} else {
		number, err := strconv.Atoi(strings.TrimPrefix(strings.ToUpper(ref), "PHM-"))
		if err != nil || number < 1 {
			return usageErr("%q is not a ticket id or number (use an id, PHM-0001 or 1)", ref)
		}
		res, err := r.client.ListTicketsFor(r.ctx, api.TicketFilter{Number: number}, 1)
		if err != nil {
			return err
		}
		if len(res.Items) == 0 {
			return newExit(ExitNotFound, "no ticket %s", ticketNumber(&number))
		}
		raw = res.Items[0]
	}
	if r.format != formatTable {
		return r.emitRaw(raw)
	}
	var tk api.Ticket
	if err := json.Unmarshal(raw, &tk); err != nil {
		return err
	}
	machine := str(tk.DeviceID)
	if tk.DeviceID != nil {
		if n := r.deviceNames()[*tk.DeviceID]; n != "" {
			machine = n + " (" + *tk.DeviceID + ")"
		}
	}
	k := &kv{}
	k.add("number", ticketNumber(tk.TicketNumber))
	k.add("id", tk.ID)
	k.add("title", str(tk.Title))
	k.add("status", tk.Status)
	k.addStyled("priority", first(strPtr(tk.Priority), "-"), sevStyle(strPtr(tk.Priority)))
	k.add("machine", machine)
	k.add("alert", str(tk.AlertID))
	k.add("assigned to", str(tk.AssignedToName))
	k.add("raised by", str(tk.CreatedByName))
	k.add("created", timeFmt(tk.CreatedAt, r.loc()))
	k.add("updated", timeFmt(tk.UpdatedAt, r.loc()))
	k.add("description", first(strPtr(tk.Description), "-"))
	renderKV(r.out(), k, r.app.io.OutTTY, r.painter())
	return nil
}
