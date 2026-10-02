/** Server-sent event replies for page tests. */
import { HttpResponse } from "msw";

/** A promise to hold a reply on until `release()`. */
export function hold() {
  let release!: () => void;
  return { held: new Promise<void>((r) => (release = r)), release: () => release() };
}

/** An SSE reply with `events` (sent after `after`), then ending, or dropping when `broken`. */
export const sse = (
  events: object[],
  { after, broken }: { after?: Promise<void>; broken?: boolean } = {},
) =>
  new HttpResponse(
    new ReadableStream({
      async start(c) {
        await after;
        for (const e of events)
          c.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`));
        if (broken) c.error(new Error("connection reset"));
        else c.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
