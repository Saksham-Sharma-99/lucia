import { useMutation, useQueryClient, type UseMutationOptions } from "@tanstack/react-query";
import { toast } from "sonner";

import { invalidate, type Operation } from "@/lib/invalidate";
import { toastError } from "@/lib/problem";

type Feedback<TData> = {
  /** Queries made stale by a success. */
  stale?: readonly Operation[];
  /** Success toast, or nothing to stay quiet. */
  success?: string | ((data: TData) => string);
  /** Error toast prefix. Pass `false` when the caller shows errors itself (e.g. on a form). */
  error?: string | false;
};

/**
 * A generated mutation plus the standard follow-up: invalidate what it made stale, toast the
 * outcome, then run the caller's own handlers.
 */
export function useApiMutation<TData, TError, TVars>(
  options: UseMutationOptions<TData, TError, TVars>,
  { stale = [], success, error = "" }: Feedback<TData> = {},
) {
  const queryClient = useQueryClient();
  return useMutation({
    ...options,
    onSuccess: (data, vars, result, context) => {
      void invalidate(queryClient, ...stale);
      const message = typeof success === "function" ? success(data) : success;
      if (message) toast.success(message);
      return options.onSuccess?.(data, vars, result, context);
    },
    onError: (e, vars, result, context) => {
      if (error !== false) toastError(e, error || undefined);
      return options.onError?.(e, vars, result, context);
    },
  });
}
