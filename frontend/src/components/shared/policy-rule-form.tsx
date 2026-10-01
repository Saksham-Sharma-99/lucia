import { PlusIcon, TrashIcon } from "lucide-react";
import { useState } from "react";

import type { PolicyRuleRef, RegistryEntryOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  TIME_PATTERN,
  defaultParams,
  label,
  options,
  orderedProperties,
  type Params,
  type Schema,
} from "@/lib/json-schema";

import { CheckboxGroup, NumberInput, SimpleSelect } from "./controls";

/** One input for a JSON Schema property: enum, array of enum, number, boolean, time, text. */
export function SchemaField({
  schema,
  value,
  onChange,
  disabled,
  invalid,
  label,
}: {
  schema: Schema;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  invalid?: boolean;
  /** The accessible name, e.g. the param's label. */
  label: string;
}) {
  if (schema.enum) {
    return (
      <SimpleSelect
        label={label}
        value={value as string}
        onChange={onChange}
        options={options(schema.enum)}
        disabled={disabled}
        invalid={invalid}
      />
    );
  }
  if (schema.type === "array" && schema.items?.enum) {
    return (
      <CheckboxGroup
        label={label}
        value={(value as string[]) ?? []}
        onChange={onChange}
        options={options(schema.items.enum)}
        disabled={disabled}
      />
    );
  }
  if (schema.type === "integer" || schema.type === "number") {
    return (
      <NumberInput
        aria-label={label}
        className="w-28"
        value={value as number}
        min={schema.minimum}
        max={schema.maximum}
        onChange={onChange}
        disabled={disabled}
        aria-invalid={invalid}
      />
    );
  }
  if (schema.type === "boolean") {
    return (
      <Switch aria-label={label} checked={!!value} onCheckedChange={onChange} disabled={disabled} />
    );
  }
  return (
    <Input
      aria-label={label}
      className={schema.pattern === TIME_PATTERN ? "w-36" : undefined}
      type={schema.pattern === TIME_PATTERN ? "time" : "text"}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      aria-invalid={invalid}
    />
  );
}

/** `{doc_kind: roles[]}` style params: rows of a key plus a value field. */
function MapParams({
  schema,
  value,
  onChange,
  disabled,
}: {
  schema: Schema;
  value: Params;
  onChange: (value: Params) => void;
  disabled?: boolean;
}) {
  const [key, setKey] = useState("");
  const entries = Object.entries(value);
  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-3">
          <code className="bg-muted w-32 shrink-0 truncate rounded px-2 py-1 font-mono text-xs">
            {k}
          </code>
          <SchemaField
            label={k}
            schema={schema}
            value={v}
            onChange={(next) => onChange({ ...value, [k]: next })}
            disabled={disabled}
          />
          {!disabled && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Remove ${k}`}
              onClick={() => onChange(Object.fromEntries(entries.filter(([x]) => x !== k)))}
            >
              <TrashIcon />
            </Button>
          )}
        </div>
      ))}
      {!disabled && (
        <div className="flex items-center gap-2">
          <Input
            className="w-48"
            value={key}
            placeholder="Document kind, e.g. hipaa_auth"
            onChange={(e) => setKey(e.target.value.replace(/[^a-z0-9_]/g, ""))}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={!key || Object.hasOwn(value, key)}
            onClick={() => {
              onChange({ ...value, [key]: [] });
              setKey("");
            }}
          >
            <PlusIcon /> Add
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * Policy rules from the registry, each with an on/off switch; turning one on reveals its
 * params, rendered from the rule's JSON Schema. The value keeps registry order.
 */
export function PolicyRuleForm({
  rules,
  value,
  onChange,
  disabled,
  errorFor,
}: {
  rules: RegistryEntryOut[];
  value: PolicyRuleRef[];
  onChange: (value: PolicyRuleRef[]) => void;
  disabled?: boolean;
  /** Error message for a field path relative to the list, e.g. `1.params.n`. */
  errorFor?: (path: string) => string | undefined;
}) {
  const enabled = new Map(value.map((r) => [r.rule, r.params ?? {}]));
  const emit = (next: Map<string, Params>) =>
    onChange(
      rules
        .filter((r) => next.has(r.name))
        .map((r) => ({ rule: r.name, params: next.get(r.name) })),
    );
  const index = (name: string) => value.findIndex((r) => r.rule === name);

  return (
    <ul className="divide-border divide-y rounded-lg border">
      {rules
        .filter((r) => r.available || enabled.has(r.name))
        .map((rule) => {
          const schema = rule.params_schema as Schema;
          const on = enabled.has(rule.name);
          const params = enabled.get(rule.name) ?? {};
          const props = orderedProperties(schema);
          const isMap = !props.length && typeof schema.additionalProperties === "object";
          const i = index(rule.name);
          return (
            <li key={rule.name} className="px-4 py-3">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{rule.display_name}</p>
                  <p className="text-muted-foreground text-sm">{rule.description}</p>
                </div>
                <Switch
                  aria-label={`Use ${rule.display_name}`}
                  checked={on}
                  disabled={disabled}
                  onCheckedChange={(checked) => {
                    const next = new Map(enabled);
                    if (checked) next.set(rule.name, defaultParams(schema));
                    else next.delete(rule.name);
                    emit(next);
                  }}
                />
              </div>
              {on && (props.length > 0 || isMap) && (
                <div className="border-brass/40 mt-3 grid gap-3 border-l-2 pl-4">
                  {isMap ? (
                    <MapParams
                      schema={schema.additionalProperties as Schema}
                      value={params}
                      disabled={disabled}
                      onChange={(p) => emit(new Map(enabled).set(rule.name, p))}
                    />
                  ) : (
                    props.map(([key, prop]) => {
                      const error = errorFor?.(`${i}.params.${key}`);
                      return (
                        <div
                          key={key}
                          className="grid items-center gap-1.5 sm:grid-cols-[9rem_1fr]"
                        >
                          <span className="text-muted-foreground text-sm">{label(key)}</span>
                          <div>
                            <SchemaField
                              label={label(key)}
                              schema={prop}
                              value={params[key]}
                              disabled={disabled}
                              invalid={!!error}
                              onChange={(v) =>
                                emit(new Map(enabled).set(rule.name, { ...params, [key]: v }))
                              }
                            />
                            {error && <p className="text-destructive mt-1 text-xs">{error}</p>}
                          </div>
                        </div>
                      );
                    })
                  )}
                  {errorFor?.(`${i}.params`) && (
                    <p className="text-destructive text-xs">{errorFor(`${i}.params`)}</p>
                  )}
                </div>
              )}
            </li>
          );
        })}
    </ul>
  );
}
