/** Display helpers shared across screens. */

/** `news_hound` → `News Hound`. */
export function titleize(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function roman(n: number): string {
  const numerals = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
  return numerals[Math.min(numerals.length - 1, Math.max(0, n))];
}

/** XP per level, mirroring `xp_rules.compute_level`. */
export const XP_PER_LEVEL = 50;

/** Tool XP per proficiency tier, mirroring `xp_rules.compute_tool_tier`. */
export const XP_PER_TOOL_TIER = 20;

export function xpIntoLevel(xp: number): number {
  return Math.max(0, xp) % XP_PER_LEVEL;
}

export function pct(value: number, max: number): string {
  return `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
}

export function classLine(mainClass: string, subClass: string | null): string {
  return titleize(mainClass) + (subClass ? ` / ${titleize(subClass)}` : "");
}

/**
 * Length of the shared prefix of two strings — used to highlight only the part
 * of a GM-suggested prompt that actually differs from the current one.
 */
export function commonPrefixLength(a: string, b: string): number {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
  return i;
}

/**
 * Turn Python's `str(annotation)` into something readable.
 *
 * `output_fields_summary` values come from `str(field.annotation)` in
 * `_agent_builder_detail`, which yields e.g. `<class 'str'>` or
 * `list[agent_kit.agents.models.news.NewsItem]`. Strip the wrapper and the
 * module path; leave anything unrecognised alone rather than guessing.
 */
export function readableAnnotation(annotation: string): string {
  const classMatch = annotation.match(/^<class '(.+)'>$/);
  const inner = classMatch ? classMatch[1] : annotation;
  return inner.replace(/\b[\w.]+\.(\w+)\b/g, "$1");
}

/** Coarse JSON type name for a sample-input value, e.g. `list[str]`. */
export function inferJsonType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) {
    const first = value[0];
    return first === undefined ? "list" : `list[${inferJsonType(first)}]`;
  }
  switch (typeof value) {
    case "string":
      return "str";
    case "boolean":
      return "bool";
    case "number":
      return Number.isInteger(value) ? "int" : "float";
    case "object":
      return "object";
    default:
      return typeof value;
  }
}

export function formatTiming(ms: number): string {
  return `${ms} ms`;
}
