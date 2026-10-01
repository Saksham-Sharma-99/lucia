import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/")({ component: Agents });

function Agents() {
  return <h1 className="text-2xl font-semibold">Agents</h1>;
}
