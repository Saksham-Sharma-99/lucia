import { SearchIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";

/**
 * A search box bound to a URL param: typing commits after 300 ms, and the box follows the URL
 * when it changes elsewhere (Back, a cleared filter).
 */
export function SearchInput({
  value,
  onCommit,
  label,
  placeholder = "Search",
}: {
  value: string | undefined;
  onCommit: (q: string | undefined) => void;
  label: string;
  placeholder?: string;
}) {
  const [text, setText] = useState(value ?? "");
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    // The URL moved without us: show what it says (React's "adjust state on prop change").
    setSynced(value);
    setText(value ?? "");
  }
  const timer = useRef<number>(undefined);
  const committed = useRef(value);
  // The URL moved without us (Back, a cleared filter): drop the pending commit so it can't undo that.
  useEffect(() => {
    if (value !== committed.current) window.clearTimeout(timer.current);
    committed.current = value;
  }, [value]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const type = (q: string) => {
    setText(q);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      committed.current = q || undefined;
      setSynced(q || undefined); // so the URL echoing this commit doesn't reset newer typing
      onCommit(q || undefined);
    }, 300);
  };

  return (
    <div className="relative w-72">
      <SearchIcon className="text-muted-foreground absolute top-2 left-2.5 size-4" aria-hidden />
      <Input
        aria-label={label}
        className="pl-8"
        placeholder={placeholder}
        value={text}
        onChange={(e) => type(e.target.value)}
      />
    </div>
  );
}
