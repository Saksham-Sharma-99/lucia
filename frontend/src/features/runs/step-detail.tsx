import { useQuery } from "@tanstack/react-query";
import { PlayIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { getStepRecordingOptions } from "@/api/generated/@tanstack/react-query.gen";
import type { StepOut } from "@/api/generated/types.gen";
import { Markdown } from "@/components/shared/markdown";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { promptDiff, roleLabel, transcriptTurns } from "./steps-model";

/**
 * What one step did: a model call's prompt (against `previous`, the role's last call) and
 * answer, or a tool's input, output and call.
 */
export function StepDetail({
  runId,
  step,
  previous,
}: {
  runId: string;
  step: StepOut;
  previous?: StepOut;
}) {
  const asked = step.input?.message;
  const text = step.output?.text;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground text-xs">
        {step.kind === "llm" ? roleLabel(step.role) : step.tool}
        {step.model && ` · ${step.model}`}
        {step.latency_ms != null && ` · ${step.latency_ms} ms`}
        {step.input_tokens != null &&
          ` · tokens ${step.input_tokens} in / ${step.output_tokens ?? 0} out`}
      </p>
      <Labeled label={step.kind === "llm" ? "Asked" : "Input"}>
        {typeof asked === "string" ? (
          <PromptView step={step} previous={previous} />
        ) : (
          <Json value={step.input ?? {}} />
        )}
      </Labeled>
      {step.tool === "vapi.place_call" && <CallArtifacts runId={runId} step={step} />}
      <Labeled label={step.kind === "llm" ? "Answered" : "Output"}>
        {typeof text === "string" ? (
          <Markdown className="bg-muted/50 max-h-[50vh] overflow-auto rounded-xl border p-4">
            {text}
          </Markdown>
        ) : (
          <Json value={step.output ?? {}} />
        )}
      </Labeled>
      {step.error && (
        <Labeled label="Error">
          <Json value={step.error} />
        </Labeled>
      )}
    </div>
  );
}

/**
 * A model call's prompt. After the role's first call, only the sections that are new or changed
 * since `previous` (prompts are rebuilt whole each call), with the full prompt a click away.
 */
export function PromptView({ step, previous }: { step: StepOut; previous?: StepOut }) {
  const [full, setFull] = useState(false);
  const prompt = String(step.input?.message ?? "");
  const before = previous?.input?.message;
  if (typeof before !== "string") return <Text>{prompt}</Text>;
  const toggle = (
    <Button size="xs" variant="ghost" onClick={() => setFull(!full)}>
      {full ? "Show changes only" : "Show full prompt"}
    </Button>
  );
  if (full)
    return (
      <div className="space-y-2">
        {toggle}
        <Text>{prompt}</Text>
      </div>
    );
  const { changed, same } = promptDiff(prompt, before);
  const role = roleLabel(step.role).toLowerCase();
  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">
        {changed.length === 0
          ? `Same prompt as the previous ${role} call.`
          : `What changed since the previous ${role} call.`}
        {same.length > 0 &&
          ` Unchanged: ${same.map((t) => t || "intro").join(", ")} (${same.length}).`}
      </p>
      {changed.map((sec, i) => (
        <Text key={i}>{sec.title ? `## ${sec.title}\n${sec.body}` : sec.body}</Text>
      ))}
      {toggle}
    </div>
  );
}

/** A Vapi call: the transcript as turns, and its recording (a fresh signed link on demand). */
export function CallArtifacts({ runId, step }: { runId: string; step: StepOut }) {
  const transcript = step.output?.transcript;
  return (
    <div className="space-y-3 rounded-xl border p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium">Call</p>
        {step.output?.ended_reason != null && (
          <span className="text-muted-foreground text-xs">
            {String(step.output.ended_reason).replaceAll("-", " ")}
          </span>
        )}
      </div>
      <CallRecording runId={runId} stepId={step.id} />
      {typeof transcript === "string" && transcript ? (
        <ol className="space-y-2">
          {transcriptTurns(transcript).map((t, i) => (
            <li
              key={i}
              aria-label={t.speaker === "agent" ? "Agent" : "Contact"}
              className={cn("flex flex-col gap-0.5", t.speaker === "contact" && "items-end")}
            >
              <span className="text-muted-foreground text-xs">
                {t.speaker === "agent" ? "Agent" : "Contact"}
              </span>
              <span
                className={cn(
                  "max-w-[80%] rounded-xl px-3 py-2",
                  t.speaker === "agent" ? "bg-muted" : "bg-primary/10",
                )}
              >
                {t.text}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted-foreground">No transcript yet.</p>
      )}
    </div>
  );
}

function CallRecording({ runId, stepId }: { runId: string; stepId: string }) {
  const [play, setPlay] = useState(false);
  const recording = useQuery({
    ...getStepRecordingOptions({ path: { run_id: runId, step_id: stepId } }),
    enabled: play,
    retry: false,
    staleTime: 60_000,
  });
  if (!play)
    return (
      <Button size="sm" variant="outline" onClick={() => setPlay(true)}>
        <PlayIcon /> Play recording
      </Button>
    );
  if (recording.isError)
    return <p className="text-muted-foreground">No recording for this call.</p>;
  if (!recording.data) return <p className="text-muted-foreground">Loading recording…</p>;
  return (
    // Calls have no captions; the transcript below is the text alternative.
    <audio
      controls
      autoPlay
      aria-label="Call recording"
      src={recording.data.url}
      className="w-full"
    />
  );
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</p>
      {children}
    </div>
  );
}

const Text = ({ children }: { children: string }) => (
  <pre className="bg-muted/50 max-h-[50vh] overflow-auto rounded-xl border p-4 font-sans text-sm whitespace-pre-wrap">
    {children}
  </pre>
);

export function Json({ value }: { value: unknown }) {
  return (
    <pre className="bg-muted/50 max-h-[60vh] overflow-auto rounded-xl border p-4 font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
