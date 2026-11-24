// a value from a table by a key that came from outside (an address, a response, what someone typed). A plain object answers for
// names it inherited ("constructor", "toString"), so a key like that would return a function and print its body on the page. This
// answers only for names the table really holds.
export function lookup<T>(table: Readonly<Record<string, T>>, key: string | null | undefined): T | undefined {
  return key != null && Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
}
