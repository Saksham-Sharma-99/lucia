import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { API, fail, http, server } from "@/test/api";
import { VERSION_CONFIG } from "@/test/fixtures";

import { toForm } from "./config";
import { useServerValidation } from "./editor";

const check = (enabled = true) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useServerValidation(toForm(VERSION_CONFIG), enabled), { wrapper }).result;
};

describe("useServerValidation", () => {
  it("is checking, then ok when the server accepts the config", async () => {
    const result = check();
    expect(result.current.state).toBe("checking");
    await waitFor(() => expect(result.current.state).toBe("ok"), { timeout: 2000 });
  });

  it("a 422 lists the server's field errors", async () => {
    const errors = [{ path: "/models/loop", code: "model", message: "Not an allowed model" }];
    server.use(http.post(`${API}/agents/validate`, () => fail(422, "Invalid config", errors)));
    const result = check();
    await waitFor(() => expect(result.current.state).toBe("invalid"), { timeout: 2000 });
    expect(result.current.errors).toEqual(errors);
  });

  it("goes quiet on a server failure rather than blocking the form", async () => {
    server.use(http.post(`${API}/agents/validate`, () => fail(500, "Boom")));
    const result = check();
    await waitFor(() => expect(result.current.state).toBe("idle"), { timeout: 2000 });
  });

  it("does nothing while disabled", () => {
    expect(check(false).current).toEqual({ state: "idle", errors: [] });
  });
});
