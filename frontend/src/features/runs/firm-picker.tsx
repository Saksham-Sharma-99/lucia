import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { listFirmsOptions } from "@/api/generated/@tanstack/react-query.gen";
import { SimpleSelect } from "@/components/shared/controls";
import { EmptyState } from "@/components/shared/empty-state";
import { buttonVariants } from "@/components/ui/button";

/** Pick one of the active firms; with none yet, point to the Firms page. */
export function FirmPicker({
  value,
  onChange,
  className,
}: {
  value: string | undefined;
  onChange: (firmId: string) => void;
  className?: string;
}) {
  const firms = useQuery(listFirmsOptions({ query: { status: "active", limit: 100 } }));
  const items = firms.data?.items ?? [];
  if (firms.isSuccess && items.length === 0)
    return (
      <EmptyState
        title="No firms yet"
        description="Agents work for a firm. Add one, connect its apps, then map an agent to it."
        action={
          <Link to="/firms" className={buttonVariants()}>
            Add a firm
          </Link>
        }
      />
    );
  return (
    <SimpleSelect
      label="Firm"
      value={value}
      onChange={onChange}
      className={className}
      options={items.map((f) => ({ value: f.id, label: f.name }))}
      placeholder="Choose a firm"
    />
  );
}
