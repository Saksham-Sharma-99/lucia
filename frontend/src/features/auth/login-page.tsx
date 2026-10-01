import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { loginMutation, getMeQueryKey } from "@/api/generated/@tanstack/react-query.gen";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { isProblem } from "@/lib/problem";

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function LoginPage({ redirect }: { redirect?: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const login = useMutation({
    ...loginMutation(),
    onSuccess: (user) => {
      queryClient.setQueryData(getMeQueryKey(), user);
      void navigate({ to: redirect || "/agents" });
    },
    onError: (error) => {
      const message =
        isProblem(error) && error.status === 429
          ? "Too many failed attempts. Wait 15 minutes and try again."
          : isProblem(error) && error.status === 401
            ? "Username or password is incorrect."
            : "Could not reach the server. Try again.";
      form.setError("root", { message });
    },
  });

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form
        noValidate
        onSubmit={form.handleSubmit((body) => login.mutate({ body }))}
        className="w-full max-w-sm"
      >
        <p className="text-brass mb-8 text-lg font-semibold tracking-tight">lucia</p>
        <h1 className="text-xl font-semibold tracking-tight">Sign in to Studio</h1>
        <p className="text-muted-foreground mt-1 mb-6 text-sm">
          Build and manage long-running agents.
        </p>
        <div className="space-y-4">
          <Field data-invalid={!!form.formState.errors.username}>
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input id="username" autoComplete="username" autoFocus {...form.register("username")} />
            <FieldError errors={[form.formState.errors.username]} />
          </Field>
          <Field data-invalid={!!form.formState.errors.password}>
            <FieldLabel htmlFor="password">Password</FieldLabel>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...form.register("password")}
            />
            <FieldError errors={[form.formState.errors.password]} />
          </Field>
          {form.formState.errors.root && (
            <p role="alert" className="text-destructive text-sm">
              {form.formState.errors.root.message}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </form>
    </main>
  );
}
