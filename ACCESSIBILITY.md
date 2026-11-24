# Accessibility

PHAEMOS is built for people who look after machines on a factory floor and for anyone who reads about them, so the dashboard, the alerts and the documentation aim to work without a mouse, without colour and without perfect eyesight. This file says what is in place today, where the gaps are and how to report a barrier.

## The dashboard

- The page language is declared and every page renders its content inside one main landmark.
- Every interactive element shows a visible focus ring, so keyboard navigation can always be followed.
- Controls are native buttons, links and inputs, reached in the order they appear on the page.
- A "Skip to content" link comes before the navigation on the website and on the dashboard.
- Animation and transitions are turned off when the device asks for reduced motion.
- The cookie banner is a non-modal dialog with a label and description. It comes first in the page order so keyboard users reach it first. Opening it from Cookie settings moves focus into it.
- Alerts can be delivered by email, SMS and webhook as well as on screen, so a critical alert never depends on watching the dashboard.

### Known gaps

- The telemetry charts are visual. Each has a title, a one-sentence description and the same numbers in a table. The readings behind them are also available through the API.
- The website and the dashboard have not yet been evaluated against WCAG 2.2 and have not been tested with a screen reader. The accessibility statement on the website says what has been checked and what has not.

## The nodes

- The wiring is documented as tables and the schematics are planned as KiCad sources, so the hardware can be read without relying on an image.
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
