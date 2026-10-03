import { useId } from "react";

import type { Registry } from "@/features/registry/use-registry";
import { hours } from "@/lib/format";
import { label } from "@/lib/json-schema";

import type { ConfigForm } from "./config";

/** What each outbound tool produces, in the builder's words. */
const OUTPUTS: Record<string, string> = {
  "gmail.send_email": "Emails sent",
  "vapi.place_call": "Calls placed, with reports",
  "slack.send_message": "Slack replies",
  "slack.post_file": "Files posted to Slack",
  "fax.send_fax": "Faxes sent",
};
/** Inbound tools that wake the agent on an event (the registry marks every inbound tool "read"). */
const TRIGGERS: Record<string, string> = {
  "slack.listen_mention": "an @mention in Slack",
  "gmail.list_inbox": "a new email in the mailbox",
  "vapi.receive_call": "a call to the firm's number",
};
const CHANNEL_LABEL: Record<string, string> = { email: "email", voice: "a call", slack: "Slack" };

const W = 480;
const X0 = 28; // left gutter: the "breaks the loop" arrow
const X1 = W - 56; // right gutter: the loop-back arrow
const CW = X1 - X0;
const GAP = 12;
const COL_W = (CW - GAP) / 2;
const LINE = 15;
const HEADING = 22; // room for a section heading above a block
const ARROW = 44; // vertical room for a labelled arrow between blocks

type Tone = "plain" | "agent" | "policy" | "muted";
/** A row of chips (model or tool names), after an optional label. */
type Chips = { label?: string; items: string[] };
type Box = { title: string; lines: string[]; chips?: Chips[]; tone?: Tone };
type Placed = Box & { x: number; y: number; w: number; h: number };
/** What a firm's mapping layers on top of the config, already in words. */
export type AtFirm = { rules: string[]; alerts: string[]; cadence?: string };

const CHIP_H = 16;
const MONO = 6; // px per character of a chip's 10px mono text

/** Characters that fit on one line of a box `w` wide (about 5.6px each at 11px). */
const fits = (w: number) => Math.floor((w - 24) / 5.6);

/**
 * A box's content, relative to its corner: its lines wrapped to width `w`, then its chip rows,
 * each chip moving to a new row when it would overflow. Sizing and drawing both use this.
 */
function layout(b: Box, w: number) {
  const lines = b.lines.flatMap((line) => wrap(line, fits(w)));
  if (!b.chips?.length) return { lines, chips: [], height: 34 + lines.length * LINE };
  const chips: { x: number; y: number; text: string; isLabel?: boolean }[] = [];
  let y = lines.length ? 29 + lines.length * LINE : 30;
  for (const row of b.chips) {
    let x = 12;
    if (row.label) {
      chips.push({ x, y, text: row.label, isLabel: true });
      x += row.label.length * 5.6 + 6;
    }
    for (const item of row.items) {
      const text = truncate(item, Math.floor((w - 36) / MONO));
      const width = text.length * MONO + 12;
      if (x > 12 && x + width > w - 12) {
        x = 12;
        y += CHIP_H + 4;
      }
      chips.push({ x, y, text });
      x += width + 4;
    }
    y += CHIP_H + 6;
  }
  return { lines, chips, height: y + 4 };
}
const boxHeight = (b: Box, w: number) => layout(b, w).height;

/** Lay boxes out two to a row (one box spans the width); returns them and the block's bottom. */
function grid(boxes: Box[], top: number): { placed: Placed[]; bottom: number } {
  const placed: Placed[] = [];
  let y = top;
  for (let i = 0; i < boxes.length; i += 2) {
    const row = boxes.slice(i, i + 2);
    const w = row.length === 1 ? CW : COL_W;
    const h = Math.max(...row.map((b) => boxHeight(b, w)));
    row.forEach((b, j) => placed.push({ ...b, x: X0 + j * (COL_W + GAP), y, w, h }));
    y += h + GAP;
  }
  return { placed, bottom: y - GAP };
}

/** A full-width box at `y`, sized to its lines. */
const wide = (box: Box, y: number): Placed => ({ ...box, x: X0, y, w: CW, h: boxHeight(box, CW) });

/**
 * How the agent works, drawn from its config: what wakes it, how it thinks, the policy check
 * every send passes, what it produces, and when it breaks out of the loop (asking a person or
 * stopping). Computed on every render; nothing is stored. `atFirm` swaps in a mapping's
 * effective rules, alert routing and cadence.
 */
export function OrchestrationDiagram({
  handle,
  config,
  registry,
  atFirm,
}: {
  handle: string;
  config: ConfigForm;
  registry: Pick<Registry, "connectors" | "rules">;
  atFirm?: AtFirm;
}) {
  const arrowId = useId();
  const tools = config.capabilities.flatMap((c) => {
    const meta = registry.connectors.find((x) => x.name === c.connector);
    return c.tools.map((name) => ({ name, meta: meta?.tools.find((t) => t.name === name) }));
  });

  const triggers: Box[] = [
    ...tools
      .filter((t) => TRIGGERS[t.name])
      .map((t) => ({
        title: t.meta?.display_name ?? t.name,
        lines: [TRIGGERS[t.name]],
        chips: [{ items: [t.name] }],
      })),
    ...followUp(config).map((b) =>
      atFirm?.cadence ? { ...b, lines: [...b.lines, atFirm.cadence] } : b,
    ),
    ...(config.recurrence
      ? [
          {
            title: `Every ${config.recurrence.every_days} days`,
            lines: [
              config.recurrence.max_cycles
                ? `starts a new round, ${config.recurrence.max_cycles} rounds in all`
                : "starts a new round",
            ],
          },
        ]
      : []),
  ];
  const reads = tools
    .filter((t) => t.meta?.direction === "inbound" && !TRIGGERS[t.name])
    .map((t) => t.name);
  const rules =
    atFirm?.rules ??
    config.policy_pack.map(
      (r) => registry.rules.find((x) => x.name === r.rule)?.display_name ?? r.rule,
    );
  const outputs: Box[] = [
    ...tools
      .filter((t) => OUTPUTS[t.name])
      .map((t) => ({ title: OUTPUTS[t.name], lines: [], chips: [{ items: [t.name] }] })),
    {
      title: "Findings and alerts",
      lines: [
        config.alert_policy.urgency_mode === "auto"
          ? "urgency decided per finding"
          : `always ${config.alert_policy.fixed_urgency}`,
        ...(atFirm?.alerts ?? []),
      ],
    },
  ];
  const end = config.end_conditions;
  const breaks: Box[] = [
    {
      title: "Asks a person",
      tone: "agent",
      lines: [
        ...config.hitl.ask_on.map((reason) => `when ${label(reason).toLowerCase()}`),
        `when unsure of a result (under ${Math.round(config.hitl.verify_evidence_below * 100)}% confident)`,
      ],
    },
    {
      title: "Stops",
      lines: [
        `when the matter closes, it ${end.on_subject_closed === "end" ? "ends" : "pauses"}`,
        `after ${end.max_duration_days} days`,
        `after ${end.max_steps} steps`,
      ],
    },
  ];

  // Top to bottom: each block is placed below the one above it, with room for a labelled arrow.
  const wakes = grid(
    triggers.length
      ? triggers
      : [{ title: "Started by hand", lines: ["no event or schedule wakes it"], tone: "muted" }],
    HEADING,
  );
  const agent = wide(
    {
      title: `@${handle}`,
      tone: "agent",
      lines: [truncate(config.system_prompt || "No system prompt yet", 60)],
      chips: [
        { label: "thinks with", items: [config.models.loop] },
        ...(reads.length ? [{ label: "can read", items: reads }] : []),
      ],
    },
    wakes.bottom + ARROW,
  );
  const policy = wide(
    {
      title: "Policy check, before every send",
      tone: "policy",
      lines: rules.length ? rules : ["No policy rules yet: add them on the Policies tab"],
      chips: [{ label: "guardrail model", items: [config.models.guardrail] }],
    },
    agent.y + agent.h + ARROW,
  );
  const produces = grid(outputs, policy.y + policy.h + ARROW + HEADING);
  const stops = grid(breaks, produces.bottom + ARROW + HEADING);
  const height = stops.bottom + 8;

  const mid = X0 + CW / 2;
  const agentMid = agent.y + agent.h / 2;
  const producesTop = produces.placed[0].y;
  const producesMid = (producesTop + produces.bottom) / 2;
  const breaksMid = (stops.placed[0].y + stops.bottom) / 2;
  const marker = `url(#${CSS.escape(arrowId)})`;

  return (
    <figure className="mx-auto max-w-lg">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="w-full"
        role="img"
        aria-label={`How @${handle} works`}
      >
        <defs>
          <marker
            id={arrowId}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="fill-muted-foreground" />
          </marker>
        </defs>

        <Heading y={14} text="Wakes up when" />
        <Heading y={producesTop - 8} text="Produces" />
        <Heading y={stops.placed[0].y - 8} text="Breaks out of the loop" />

        <Arrow x={mid} from={wakes.bottom} to={agent.y} text="wakes the agent" marker={marker} />
        <Arrow
          x={mid}
          from={agent.y + agent.h}
          to={policy.y}
          text="decides on an action"
          marker={marker}
        />
        <Arrow
          x={mid}
          from={policy.y + policy.h}
          to={producesTop - HEADING}
          text="if every rule allows it"
          marker={marker}
        />

        {/* Loop back: after acting, the agent waits for the next trigger. */}
        <path
          d={`M${X1},${producesMid} H${W - 18} V${agentMid} H${X1}`}
          className="stroke-muted-foreground fill-none"
          strokeWidth={1.25}
          markerEnd={marker}
        />
        <SideLabel
          x={W - 6}
          y={(agentMid + producesMid) / 2}
          text="then waits for the next trigger"
        />

        {/* Out of the loop: to a person, or to a stop. */}
        <path
          d={`M${X0},${agentMid} H10 V${breaksMid} H${X0}`}
          className="stroke-brass fill-none"
          strokeWidth={1.25}
          strokeDasharray="4 3"
          markerEnd={marker}
        />
        <SideLabel x={6} y={(agentMid + breaksMid) / 2} text="breaks the loop" brass />

        {[...wakes.placed, agent, policy, ...produces.placed, ...stops.placed].map((b, i) => (
          <BoxView key={i} box={b} />
        ))}
      </svg>
    </figure>
  );
}

function Heading({ y, text }: { y: number; text: string }) {
  return (
    <text x={X0} y={y} className="fill-muted-foreground text-[11px] font-medium">
      {text}
    </text>
  );
}

function Arrow({
  x,
  from,
  to,
  text,
  marker,
}: {
  x: number;
  from: number;
  to: number;
  text: string;
  marker: string;
}) {
  return (
    <g>
      <line
        x1={x}
        y1={from + 2}
        x2={x}
        y2={to - 2}
        className="stroke-muted-foreground"
        strokeWidth={1.25}
        markerEnd={marker}
      />
      <text x={x + 8} y={(from + to) / 2 + 4} className="fill-muted-foreground text-[10.5px]">
        {text}
      </text>
    </g>
  );
}

/** A label running up a gutter arrow. */
function SideLabel({ x, y, text, brass }: { x: number; y: number; text: string; brass?: boolean }) {
  return (
    <text
      transform={`translate(${x},${y}) rotate(-90)`}
      textAnchor="middle"
      className={`text-[10.5px] ${brass ? "fill-brass" : "fill-muted-foreground"}`}
    >
      {text}
    </text>
  );
}

const STROKE: Record<Tone, string> = {
  plain: "stroke-border",
  agent: "stroke-brass",
  policy: "stroke-muted-foreground",
  muted: "stroke-border",
};

function BoxView({ box: b }: { box: Placed }) {
  const chars = fits(b.w);
  const { lines, chips } = layout(b, b.w);
  const isAgent = b.title.startsWith("@");
  return (
    <g>
      <rect
        x={b.x}
        y={b.y}
        width={b.w}
        height={b.h}
        rx={8}
        className={`fill-card drop-shadow-md ${STROKE[b.tone ?? "plain"]}`}
        strokeWidth={isAgent ? 1.5 : 1}
        strokeDasharray={b.tone === "policy" ? "5 4" : undefined}
      />
      <text
        x={b.x + 12}
        y={b.y + 20}
        className={
          isAgent
            ? "fill-brass font-mono text-[13px] font-semibold"
            : "fill-foreground text-[12px] font-medium"
        }
      >
        {truncate(b.title, chars)}
      </text>
      {lines.map((line, i) => (
        <text
          key={i}
          x={b.x + 12}
          y={b.y + 36 + i * LINE}
          className={`fill-muted-foreground text-[11px] ${b.tone === "muted" ? "italic" : ""}`}
        >
          {line}
        </text>
      ))}
      {chips.map((c, i) =>
        c.isLabel ? (
          <text
            key={i}
            x={b.x + c.x}
            y={b.y + c.y + 11.5}
            className="fill-muted-foreground text-[11px]"
          >
            {c.text}
          </text>
        ) : (
          <g key={i}>
            <rect
              x={b.x + c.x}
              y={b.y + c.y}
              width={c.text.length * MONO + 12}
              height={CHIP_H}
              rx={CHIP_H / 2}
              className="fill-muted stroke-border"
            />
            <text
              x={b.x + c.x + 6}
              y={b.y + c.y + 11.5}
              className="fill-foreground font-mono text-[10px]"
            >
              {c.text}
            </text>
          </g>
        ),
      )}
    </g>
  );
}

/** The follow-up schedule as a trigger: each step that wakes the agent to contact again. */
function followUp(config: ConfigForm): Box[] {
  const fu = config.follow_up;
  if (fu.mode === "fixed_ladder")
    return [
      {
        title: "Follow-up schedule",
        lines: fu.ladder.map((r) =>
          r.kind === "channel"
            ? `${r.wait_hours ? `after ${hours(r.wait_hours)}` : "right away"}: ${CHANNEL_LABEL[r.channel ?? ""] ?? r.channel}, up to ${r.attempts}×`
            : `then ${r.action === "escalate" ? "escalate" : "flag"} (${r.urgency ?? "P1"} alert)`,
        ),
      },
    ];
  if (fu.mode === "dynamic") {
    const d = fu.dynamic;
    return [
      {
        title: "Follow-up, timed by the agent",
        lines: [
          `every ${hours(d.min_hours)}–${hours(d.max_hours)}`,
          `by ${d.channels.map((c) => CHANNEL_LABEL[c] ?? c).join(" or ") || "no channel yet"}`,
          d.business_hours ? "in business hours" : "at any time",
          `escalates after ${d.escalate_after.attempts} tries (${d.escalate_after.urgency})`,
        ],
      },
    ];
  }
  return [];
}

/** Greedy word wrap; a single overlong word is cut. */
function wrap(text: string, n: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    if (line && `${line} ${word}`.length > n) {
      out.push(line);
      line = "";
    }
    line = line ? `${line} ${word}` : truncate(word, n);
  }
  return line ? [...out, line] : out;
}

function truncate(text: string, n: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > n ? `${flat.slice(0, n - 1)}…` : flat;
}
