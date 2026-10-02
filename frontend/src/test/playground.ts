/** MSW handlers for the playground pages. */
import { API, HttpResponse, firm, http, page, server } from "./api";
import { conversation, mentionable } from "./runtime";

export const TODAY = new Date().toISOString();

export function playgroundApi({
  chats = [conversation({ last_message_at: TODAY })],
  asked = [] as URLSearchParams[],
} = {}) {
  server.use(
    http.get(`${API}/firms`, () =>
      HttpResponse.json(page([firm(), firm({ id: "f2", name: "Smith & Associates" })])),
    ),
    http.get(`${API}/firms/:firmId/conversations`, ({ request }) => {
      asked.push(new URL(request.url).searchParams);
      return HttpResponse.json(page(chats));
    }),
    http.get(`${API}/firms/:firmId/mentionable-agents`, () => HttpResponse.json([mentionable()])),
  );
  return asked;
}
