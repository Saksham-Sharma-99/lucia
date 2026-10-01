export const CONNECTOR_NAMES: Record<string, string> = {
  slack: "Slack",
  gmail: "Gmail",
  vapi: "Voice (Vapi)",
  fax: "Fax",
};

/** What kind of app each connector is, shown above its name. */
export const CONNECTOR_KIND: Record<string, string> = {
  slack: "Chat",
  gmail: "Email",
  vapi: "Voice calls",
  fax: "Fax",
};
