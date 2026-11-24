# Tickets Page

Route: `/tickets`
Shows the newest 200 tickets with status and priority filters in the query string. `?ticket=<id>` opens a ticket in a detail panel where status, priority and assignee can be changed through `PATCH /tickets/{id}`.
Logic: `lib/ticketView.ts`. Components: `components/tickets/`.
