import { client } from "@/api/generated/client.gen";

/** Configure the generated client once: cookie session plus the CSRF header the API requires. */
export function configureApi(baseUrl = import.meta.env.VITE_API_URL ?? "") {
  client.setConfig({
    baseUrl,
    credentials: "include",
    headers: { "X-Requested-With": "lucia" },
  });
}
