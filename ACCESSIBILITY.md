# Accessibility

PHAEMOS is operated by technicians on a factory floor and read by anyone who looks after the machines, so the dashboard, the alerts and the documentation aim to work without a mouse, without colour and without perfect eyesight. This file says what is in place today, where the gaps are and how to report a barrier.

## The dashboard

- The page language is declared and every page renders its content inside one main landmark.
- Every interactive element shows a visible focus ring, so keyboard navigation can always be followed.
- Controls are native buttons, links and inputs, reached in the order they appear on the page.
- The cookie consent is a labelled region, so a screen reader announces what it is.
- Alerts can be delivered by email, SMS and webhook as well as on screen, so a critical alert never depends on watching the dashboard.

### Known gaps

- There is no "Skip to content" link yet.
- Animation does not yet follow the `prefers-reduced-motion` setting.
- The telemetry charts are visual. The readings behind them are available through the API.

## The nodes

- The wiring is documented as tables and the schematics ship as KiCad sources, so the hardware can be read without relying on an image.
- Each node reports its state over its network link, so a node's health is readable from the dashboard rather than only from its LED.

## Documentation

Documentation in this repository and the published component repositories aims to:

- Use a real heading outline, so screen readers and the page outline can jump between sections.
- Use link text that says where the link goes, never "click here".
- Give images, diagrams and badges alt text. Write diagrams as Mermaid where possible, so their content is text.
- Show code, commands and output as text, never as screenshots.
- Never rely on colour alone: callouts carry a label such as Note, Tip or Warning.
- Use plain language, explaining a term where it first appears.

## Reporting a barrier

Open an [issue](https://github.com/phaemos/phaemos/issues/new/choose) with the `accessibility` label. Say what you were trying to do, what happened and what would have worked better. If the assistive technology or the settings you use are relevant, mention them too. Accessibility problems are treated as bugs.
