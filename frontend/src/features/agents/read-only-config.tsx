import { useMemo, type ReactNode } from "react";
import { FormProvider, useForm } from "react-hook-form";

import type { VersionConfig } from "@/api/generated/types.gen";

import { toForm, type ConfigForm } from "./config";
import type { AgentForm } from "./sections";

/**
 * Feeds the section views (which read `config.*` from form context) a stored version, read-only.
 * Disabled inputs keep full contrast so the values stay legible.
 */
export function ReadOnlyConfig({
  config: stored,
  children,
}: {
  config: VersionConfig;
  children: (config: ConfigForm) => ReactNode;
}) {
  const config = useMemo(() => toForm(stored), [stored]);
  const form = useForm<AgentForm>({
    values: { handle: "", name: "", description: "", use_cases: [], config, changelog: "" },
  });
  return (
    <FormProvider {...form}>
      {/* `contents`: no box of its own, so it doesn't break the parent's layout. */}
      <div className="contents [&_:disabled]:cursor-default [&_:disabled]:opacity-100 [&_[data-disabled]]:opacity-100">
        {children(config)}
      </div>
    </FormProvider>
  );
}
