import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApiMutation } from "./use-api-mutation";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const setup = <T,>(
  mutationFn: () => Promise<T>,
  feedback: Parameters<typeof useApiMutation>[1],
  onSuccess = vi.fn(),
  onError = vi.fn(),
) => {
  const client = new QueryClient();
  client.setQueryData([{ _id: "listAgents" }], []);
  client.setQueryData([{ _id: "listFirms" }], []);
  const stale = (id: string) => client.getQueryState([{ _id: id }])?.isInvalidated;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () => useApiMutation({ mutationFn, onSuccess, onError }, feedback),
    { wrapper },
  );
  return { result, stale, onSuccess, onError };
};

describe("useApiMutation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("on success: invalidates, toasts from the data, then runs the caller's handler", async () => {
    const { result, stale, onSuccess } = setup(async () => ({ name: "a" }), {
      stale: ["listAgents"],
      success: (d) => `Saved ${(d as { name: string }).name}`,
    });
    await act(() => result.current.mutateAsync(undefined));
    expect(stale("listAgents")).toBe(true);
    expect(stale("listFirms")).toBe(false);
    expect(toast.success).toHaveBeenCalledWith("Saved a");
    expect(onSuccess).toHaveBeenCalledOnce();
  });

  it("on error: toasts unless the caller shows errors itself", async () => {
    const fail = async () => Promise.reject(new Error("nope"));
    const loud = setup(fail, { error: "Save failed" });
    await act(() => loud.result.current.mutateAsync(undefined).catch(() => {}));
    expect(toast.error).toHaveBeenCalledExactlyOnceWith("Save failed: nope");
    expect(loud.onError).toHaveBeenCalledOnce();

    vi.clearAllMocks();
    const quiet = setup(fail, { error: false });
    await act(() => quiet.result.current.mutateAsync(undefined).catch(() => {}));
    expect(toast.error).not.toHaveBeenCalled();
    expect(quiet.onError).toHaveBeenCalledOnce();
  });
});
