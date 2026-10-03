import { describe, it } from "vitest";

import { API, HttpResponse, firm, http, page, server } from "@/test/api";
import { renderWithClient, screen } from "@/test/app";

import { FirmPicker } from "./firm-picker";
import { FIRM_KEY, useFirm } from "./use-firm";

function Harness({ fromUrl }: { fromUrl?: string }) {
  const { firmId, setFirm } = useFirm(fromUrl);
  return (
    <>
      <p>firm: {firmId ?? "none"}</p>
      <FirmPicker value={firmId} onChange={setFirm} />
    </>
  );
}

const twoFirms = () =>
  server.use(
    http.get(`${API}/firms`, () =>
      HttpResponse.json(page([firm(), firm({ id: "f2", name: "Smith & Associates" })])),
    ),
  );

describe("firm choice", () => {
  it("the URL wins over the remembered firm", async () => {
    twoFirms();
    localStorage.setItem(FIRM_KEY, "f1");
    renderWithClient(<Harness fromUrl="f2" />);
    await screen.findByText("firm: f2");
  });

  it("falls back to the remembered firm, then the first one", async () => {
    twoFirms();
    localStorage.setItem(FIRM_KEY, "f2");
    const first = renderWithClient(<Harness />);
    await screen.findByText("firm: f2");
    first.unmount();
    localStorage.setItem(FIRM_KEY, "gone");
    renderWithClient(<Harness />);
    await screen.findByText("firm: f1");
  });
});
