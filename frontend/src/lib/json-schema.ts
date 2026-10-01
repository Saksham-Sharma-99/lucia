/** Just enough JSON Schema to render registry policy-rule params as form fields. */

export type Schema = {
  type?: string;
  enum?: string[];
  items?: Schema;
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: Schema | boolean;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  description?: string;
};
export type Params = Record<string, unknown>;

export const TIME_PATTERN = "^([01]\\d|2[0-3]):[0-5]\\d$";
export const options = (values: string[]) => values.map((v) => ({ value: v, label: v }));
const LABELS: Record<string, string> = {
  n: "Limit",
  tz: "Timezone",
  start: "Starts",
  end: "Ends",
  channel: "Channels",
  roles: "Roles",
};
export const label = (key: string) =>
  LABELS[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Schema properties in their intended order. JSONB storage re-sorts object keys, so the
 *  `required` list (which keeps author order) comes first. */
export function orderedProperties(schema: Schema): [string, Schema][] {
  const props = schema.properties ?? {};
  const order = [...(schema.required ?? []), ...Object.keys(props)];
  return [...new Set(order)].filter((k) => k in props).map((k) => [k, props[k]]);
}

/** Sensible starting params for a rule, so enabling it yields something valid to edit. */
export function defaultParams(schema: Schema): Params {
  const out: Params = {};
  for (const [key, prop] of orderedProperties(schema)) {
    if (prop.enum) out[key] = prop.enum[0];
    else if (prop.type === "array") out[key] = prop.items?.enum ? [prop.items.enum[0]] : [];
    else if (prop.type === "integer" || prop.type === "number") out[key] = prop.minimum ?? 1;
    else if (prop.type === "boolean") out[key] = false;
    else if (prop.pattern === TIME_PATTERN) out[key] = key === "start" ? "20:00" : "08:00";
    else out[key] = "";
  }
  return out;
}

/** A one-line description of a rule's settings, e.g. "n: integer; tz: recipient | firm". */
/** One param's allowed values or type, e.g. "P0 | P1" or "integer". */
export const paramSummary = (p: Schema): string =>
  p.enum?.join(" | ") ??
  (p.items?.enum
    ? `[${p.items.enum.join(", ")}]`
    : p.pattern === TIME_PATTERN
      ? "time (HH:MM)"
      : String(p.type));

export function paramsSummary(schema: Schema): string {
  const props = orderedProperties(schema);
  if (props.length) return props.map(([k, p]) => `${k}: ${paramSummary(p)}`).join("; ");
  return typeof schema.additionalProperties === "object"
    ? "roles per document kind"
    : "no settings";
}
