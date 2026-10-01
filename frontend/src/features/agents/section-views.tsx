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

type Props = { registry: Registry; disabled?: boolean };

/** Each editing section's form, so the wizard, the amend tabs and the detail tabs render alike. */
export const SECTION_VIEWS: Record<SectionId, (p: Props) => ReactNode> = {
  basic: ({ disabled }) => <BasicSection disabled={disabled} />,
  capabilities: (p) => <CapabilitiesSection {...p} />,
  prompt: (p) => <PromptSection {...p} />,
  policies: (p) => <PoliciesSection {...p} />,
  schedules: (p) => <SchedulesSection {...p} />,
};
