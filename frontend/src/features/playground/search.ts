import { z } from "zod";

/** Search params shared by the playground routes. */
export const playgroundSearch = z.object({
  firm: z.string().optional().catch(undefined),
  drawer: z.string().optional().catch(undefined),
  subject: z.boolean().optional().catch(undefined),
});
