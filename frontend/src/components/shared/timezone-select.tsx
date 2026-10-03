import { useQuery } from "@tanstack/react-query";

import { listTimezonesOptions } from "@/api/generated/@tanstack/react-query.gen";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";

/** Pick an IANA timezone the API accepts (it serves the list); type to search, e.g. "kolkata".
 * `""` is no zone, offered only when `clearable`. */
export function TimezoneSelect({
  id,
  value,
  onChange,
  clearable,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (zone: string) => void;
  clearable?: boolean;
  invalid?: boolean;
}) {
  const zones = useQuery({ ...listTimezonesOptions(), staleTime: Infinity }).data ?? [];
  return (
    <Combobox
      items={zones}
      value={value || null}
      onValueChange={(z: string | null) => onChange(z ?? "")}
    >
      <ComboboxInput
        id={id}
        className="w-full"
        placeholder="Search a timezone, e.g. America/New_York"
        aria-invalid={invalid}
        showClear={clearable && !!value}
      />
      <ComboboxContent>
        <ComboboxEmpty>No timezone matches</ComboboxEmpty>
        <ComboboxList>
          {(zone: string) => (
            <ComboboxItem key={zone} value={zone}>
              {zone}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
