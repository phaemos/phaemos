'use client';

// TODO: wire up to POST /api/v1/tickets when auth flow is complete

// I stub the form now so the route renders something and the ticket table
// has a sibling component to pair with - an empty route page looks broken
// during development and makes it harder to test layout.

export default function TicketForm() {
  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // I log to the console rather than throwing an error so the stub does not
    // cause unhandled rejections during development.
    console.log('TODO: implement ticket creation');
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 bg-white/5 border border-gray-700 rounded-xl p-6"
    >
      <h2 className="text-base font-semibold text-gray-200">New Ticket</h2>

      <div>
        <label
          htmlFor="ticket-title"
          className="block text-xs font-medium text-gray-400 mb-1"
        >
          Title
        </label>
        <input
          id="ticket-title"
          name="title"
          type="text"
          placeholder="Short description of the issue"
          className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label
          htmlFor="ticket-description"
          className="block text-xs font-medium text-gray-400 mb-1"
        >
          Description
        </label>
        <textarea
          id="ticket-description"
          name="description"
          rows={4}
          placeholder="Detailed explanation of the fault or maintenance required"
          className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>

      <div>
        <label
          htmlFor="ticket-priority"
          className="block text-xs font-medium text-gray-400 mb-1"
        >
          Priority
        </label>
        <select
          id="ticket-priority"
          name="priority"
          className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Select priority</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      <div>
        <label
          htmlFor="ticket-device-id"
          className="block text-xs font-medium text-gray-400 mb-1"
        >
          Device ID
        </label>
        <input
          id="ticket-device-id"
          name="device_id"
          type="text"
          placeholder="UUID of the associated device"
          className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
        />
      </div>

      <button
        type="submit"
        className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        Submit Ticket
      </button>
    </form>
  );
}
