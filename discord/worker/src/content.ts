// the shape of discord/content/commands.toml after the build step turns it into json.
export interface Link {
  label: string;
  url: string;
}

export interface Topic {
  key: string;
  title: string;
  lines: string[];
  links: Link[];
}

export interface CommandDef {
  name: string;
  type?: "chat_input" | "message";
  description?: string;
  help?: string;
  visibility: "private" | "public";
  share?: boolean;
  staff?: boolean;
}

export interface Content {
  schema: 1;
  project: {
    name: string;
    slug: string;
    repository: string;
    site: string;
    releases: string;
    issue_form: string;
    security_form: string;
    security_email: string;
    contact_email: string;
    commands_channel?: string;
    contact_page?: string;
    contributing: string;
    first_issues: string;
    run_locally: string;
  };
  status?: { url: string; page: string };
  commands: CommandDef[];
  docs: Topic[];
  faq: Topic[];
  hardware: Topic[];
  bug: { lines: string[]; links: Link[] };
  security: { lines: string[]; links: Link[]; email: string };
  contribute: { lines: string[]; links: Link[] };
  roles: { lines: string[]; links: Link[] };
  ticket_kinds: { key: string; title: string }[];
  ticket: { lines: string[] };
  mod_guide: { key: string; title: string; steps: string[] }[];
  mod_reply: { key: string; text: string }[];
}
