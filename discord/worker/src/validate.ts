// checks the command content against Discord's limits and our own writing rules.
// used by the build step and by the tests, so a bad text never reaches a deploy.

const DASHES = /[\u2013\u2014\u2012\u2015]/;
const COMMA_BEFORE_JOINER = /,\s+(and|or)\b/i;
const EMOJI = /\p{Extended_Pictographic}/u;
const DIGIT_RUN = /\d{17,20}/;
const CHOICE_LISTS = ["docs", "faq", "hardware", "mod_guide", "mod_reply", "ticket_kinds"] as const;

type Rec = Record<string, unknown>;

function isRec(v: unknown): v is Rec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function walkStrings(value: unknown, path: string, visit: (s: string, path: string) => void): void {
  if (typeof value === "string") visit(value, path);
  else if (Array.isArray(value)) {
    for (const [i, v] of value.entries()) walkStrings(v, `${path}[${i}]`, visit);
  } else if (isRec(value)) for (const [k, v] of Object.entries(value)) walkStrings(v, `${path}.${k}`, visit);
}

function checkLinks(list: unknown, where: string, problems: string[]): void {
  if (!Array.isArray(list)) {
    problems.push(`${where}: links must be a list`);
    return;
  }
  for (const l of list) {
    if (!isRec(l) || typeof l.label !== "string" || typeof l.url !== "string") {
      problems.push(`${where}: a link needs a label and a url`);
      continue;
    }
    if (!/^https:\/\/[^\s<>]+$/.test(l.url))
      problems.push(`${where}: link ${l.label} must be a plain https address`);
  }
}

function checkOption(o: unknown, where: string, c: Rec, problems: string[]): void {
  if (!isRec(o)) return;
  const name = o.name;
  if (typeof name !== "string" || !/^[a-z0-9_-]{1,32}$/.test(name))
    problems.push(`${where}: bad option name`);
  if (typeof o.description !== "string" || o.description.length < 1 || o.description.length > 100) {
    problems.push(`${where}.${String(name)}: description must be 1 to 100 characters`);
  }
  if (!["string", "integer", "user", "boolean"].includes(String(o.type)))
    problems.push(`${where}.${String(name)}: bad type`);
  if (typeof o.choices_from === "string") {
    const list = c[o.choices_from];
    if (!Array.isArray(list) || list.length === 0 || list.length > 25) {
      problems.push(`${where}.${String(name)}: choices_from must name a list of 1 to 25 items`);
    } else {
      for (const item of list) {
        if (!isRec(item) || typeof item.key !== "string" || item.key.length > 100)
          problems.push(`${where}: a choice has a bad key`);
        else if (typeof item.title === "string" && item.title.length > 100)
          problems.push(`${where}: choice ${item.key} title is over 100 characters`);
      }
    }
  }
}

export function validateContent(input: unknown): string[] {
  const problems: string[] = [];
  if (!isRec(input)) return ["the file must be a table"];
  const c = input;
  if (c.schema !== 1) problems.push("schema must be 1");

  const project = isRec(c.project) ? c.project : {};
  for (const k of [
    "name",
    "slug",
    "repository",
    "site",
    "releases",
    "issue_form",
    "security_form",
    "contributing",
    "first_issues",
    "run_locally",
    "contact_page",
  ]) {
    if (typeof project[k] !== "string" || project[k] === "") problems.push(`project.${k} is missing`);
  }
  if (
    typeof project.repository === "string" &&
    !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(project.repository)
  ) {
    problems.push("project.repository must look like owner/name");
  }
  for (const k of [
    "site",
    "releases",
    "issue_form",
    "security_form",
    "contributing",
    "first_issues",
    "run_locally",
  ]) {
    if (typeof project[k] === "string" && !/^https:\/\/[^\s<>]+$/.test(project[k]))
      problems.push(`project.${k} must be a plain https address`);
  }
  if (project.commands_channel !== undefined && !/^[a-z0-9-]{1,100}$/.test(String(project.commands_channel)))
    problems.push("project.commands_channel must be a channel name in lower case with hyphens");
  for (const k of ["security_email", "contact_email"]) {
    if (typeof project[k] !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(project[k]))
      problems.push(`project.${k} must be an email address`);
  }
  if (c.status !== undefined) {
    const s = isRec(c.status) ? c.status : {};
    for (const k of ["url", "page"]) {
      if (typeof s[k] !== "string" || !/^https:\/\/[^\s<>]+$/.test(s[k]))
        problems.push(`status.${k} must be a plain https address`);
    }
  }

  const commands = Array.isArray(c.commands) ? c.commands : [];
  if (commands.length === 0 || commands.length > 100) problems.push("commands must hold 1 to 100 entries");
  const seen = new Set<string>();
  let staffOk = true;
  for (const cmd of commands) {
    if (!isRec(cmd) || typeof cmd.name !== "string") {
      problems.push("a command has no name");
      continue;
    }
    const where = `commands.${cmd.name}`;
    const type = cmd.type ?? "chat_input";
    if (seen.has(`${type}:${cmd.name}`)) problems.push(`${where}: duplicate`);
    seen.add(`${type}:${cmd.name}`);
    if (cmd.name.length < 1 || cmd.name.length > 32)
      problems.push(`${where}: name must be 1 to 32 characters`);
    if (type === "chat_input") {
      if (!/^[a-z0-9_-]+$/.test(cmd.name)) problems.push(`${where}: a slash command name is lower case`);
      if (typeof cmd.description !== "string" || cmd.description.length < 1 || cmd.description.length > 100)
        problems.push(`${where}: description must be 1 to 100 characters`);
    } else if (type !== "message") problems.push(`${where}: bad type`);
    if (cmd.visibility !== "private" && cmd.visibility !== "public")
      problems.push(`${where}: visibility must be private or public`);
    if (cmd.help !== undefined && (typeof cmd.help !== "string" || cmd.help.length > 200))
      problems.push(`${where}: help is too long`);
    const opts = Array.isArray(cmd.options) ? cmd.options : [];
    if (opts.length > 25) problems.push(`${where}: too many options`);
    for (const o of opts) checkOption(o, where, c, problems);
    const subs = Array.isArray(cmd.subcommands) ? cmd.subcommands : [];
    for (const sub of subs) {
      if (!isRec(sub)) continue;
      for (const o of Array.isArray(sub.options) ? sub.options : []) {
        checkOption(o, `${where}.${String(sub.name)}`, c, problems);
      }
    }
    if (cmd.name === "mod" && cmd.staff !== true) staffOk = false;
  }
  if (!staffOk) problems.push("the mod command must be marked staff");

  for (const key of ["docs", "faq", "hardware"] as const) {
    const list = Array.isArray(c[key]) ? (c[key] as unknown[]) : [];
    if (list.length === 0) problems.push(`${key} is empty`);
    const keys = new Set<string>();
    for (const t of list) {
      if (!isRec(t) || typeof t.key !== "string" || typeof t.title !== "string") {
        problems.push(`${key}: a topic needs a key and a title`);
        continue;
      }
      if (!/^[a-z0-9-]{1,100}$/.test(t.key))
        problems.push(`${key}.${t.key}: key must be lower case with hyphens`);
      if (keys.has(t.key)) problems.push(`${key}.${t.key}: duplicate`);
      keys.add(t.key);
      if (!Array.isArray(t.lines) || t.lines.length !== 2)
        problems.push(`${key}.${t.key}: it needs exactly two lines`);
      checkLinks(t.links, `${key}.${t.key}`, problems);
      const total = [
        t.title,
        ...(Array.isArray(t.lines) ? t.lines : []),
        ...(Array.isArray(t.links) ? t.links.map((l) => `${(l as Rec).label}: <${(l as Rec).url}>`) : []),
      ].join("\n");
      if (total.length > 2000) problems.push(`${key}.${t.key}: the answer is over 2000 characters`);
    }
  }
  for (const key of ["bug", "security", "contribute", "roles"] as const) {
    const t = isRec(c[key]) ? (c[key] as Rec) : {};
    if (!Array.isArray(t.lines) || t.lines.length === 0) problems.push(`${key}.lines is missing`);
    checkLinks(t.links, key, problems);
    if (JSON.stringify(t).length > 1900) problems.push(`${key}: the answer is too long`);
  }
  if (!isRec(c.security) || typeof c.security.email !== "string") problems.push("security.email is missing");
  const kinds = Array.isArray(c.ticket_kinds) ? c.ticket_kinds : [];
  if (kinds.length < 1 || kinds.length > 5) problems.push("ticket_kinds must hold 1 to 5 kinds");
  for (const k of kinds) {
    if (!isRec(k) || typeof k.key !== "string" || !/^[a-z0-9-]{1,50}$/.test(k.key))
      problems.push("a ticket kind needs a lower case key");
    else if (typeof k.title !== "string" || k.title.length < 1 || k.title.length > 20)
      problems.push(`ticket_kinds.${k.key}: the title is the tag name and is 1 to 20 characters`);
  }
  const ticket = isRec(c.ticket) ? c.ticket : {};
  if (!Array.isArray(ticket.lines) || ticket.lines.length === 0) problems.push("ticket.lines is missing");
  else if (JSON.stringify(ticket).length > 1900) problems.push("ticket: the answer is too long");
  for (const g of Array.isArray(c.mod_guide) ? c.mod_guide : []) {
    if (!isRec(g) || !Array.isArray(g.steps) || g.steps.length === 0) problems.push("a guide needs steps");
    else if (JSON.stringify(g).length > 1900) problems.push(`mod_guide.${String(g.key)}: too long`);
  }
  for (const r of Array.isArray(c.mod_reply) ? c.mod_reply : []) {
    if (!isRec(r) || typeof r.text !== "string" || r.text.length > 1900)
      problems.push("a reply template is missing or too long");
  }
  for (const list of CHOICE_LISTS) if (!Array.isArray(c[list])) problems.push(`${list} is missing`);

  walkStrings(c, "content", (s, path) => {
    if (DASHES.test(s)) problems.push(`${path}: a long dash`);
    if (COMMA_BEFORE_JOINER.test(s)) problems.push(`${path}: a comma before and or or`);
    if (EMOJI.test(s)) problems.push(`${path}: an emoji`);
    if (DIGIT_RUN.test(s)) problems.push(`${path}: a run of 17 to 20 digits`);
    if (/webhooks\//i.test(s)) problems.push(`${path}: looks like a webhook address`);
  });
  return problems;
}
