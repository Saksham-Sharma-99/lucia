const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["week", 604_800],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const seconds = (new Date(iso).getTime() - now) / 1000;
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function dateTime(iso: string | null | undefined): string {
  return iso
    ? new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}

/** 49 -> "2d 1h", 24 -> "1d", 5 -> "5h", 0 -> "now" */
export function hours(h: number): string {
  if (h === 0) return "now";
  const d = Math.floor(h / 24);
  const r = h % 24;
  return [d && `${d}d`, r && `${r}h`].filter(Boolean).join(" ");
}

export function initials(text: string): string {
  const words = text
    .replace(/[^a-zA-Z0-9 ]/g, " ")
    .trim()
    .split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? words[0]?.[1] ?? "")).toUpperCase();
}

const HUES = [38, 152, 212, 262, 336, 18, 188];

/** A stable colour per handle, so an agent keeps its colour everywhere. */
export function hueFor(key: string): number {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return HUES[h % HUES.length];
}

export function shortHash(hash: string): string {
  return hash.slice(0, 8);
}
