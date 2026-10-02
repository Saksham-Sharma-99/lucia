import type { ReactNode } from "react";

import type { Registry } from "@/features/registry/use-registry";

import type { SectionId } from "./editor";
import {
  BasicSection,
  CapabilitiesSection,
  PoliciesSection,
  PromptSection,
  SchedulesSection,
} from "./sections";

/** `assist` goes above the prompt box (the AI wand); other sections don't take it. */
type Props = { registry: Registry; disabled?: boolean; assist?: ReactNode };

/** Each editing section's form, so the wizard, the amend tabs and the detail tabs render alike. */
export const SECTION_VIEWS: Record<SectionId, (p: Props) => ReactNode> = {
  basic: ({ disabled }) => <BasicSection disabled={disabled} />,
  capabilities: ({ registry, disabled }) => (
    <CapabilitiesSection registry={registry} disabled={disabled} />
  ),
  prompt: (p) => <PromptSection {...p} />,
  policies: ({ registry, disabled }) => <PoliciesSection registry={registry} disabled={disabled} />,
  schedules: ({ registry, disabled }) => (
    <SchedulesSection registry={registry} disabled={disabled} />
  ),
};
