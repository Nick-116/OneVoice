import { useMemo } from 'react';
import { allTimeZones, COMMON_US_ZONES } from '../lib/time';
import type { Campus, Language } from '../types';
import { Checkbox, Select } from './ui';

export function TimezoneSelect({ id, value, onChange }: { id?: string; value: string; onChange: (tz: string) => void }) {
  const all = useMemo(() => allTimeZones().filter((z) => !COMMON_US_ZONES.includes(z)), []);
  const known = COMMON_US_ZONES.includes(value) || all.includes(value);
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {!known && value && <option value={value}>{value}</option>}
      <optgroup label="Common (US)">
        {COMMON_US_ZONES.map((z) => (
          <option key={z} value={z}>
            {z.replace(/_/g, ' ')}
          </option>
        ))}
      </optgroup>
      <optgroup label="All time zones">
        {all.map((z) => (
          <option key={z} value={z}>
            {z.replace(/_/g, ' ')}
          </option>
        ))}
      </optgroup>
    </Select>
  );
}

export function CampusSelect({
  id,
  campuses,
  value,
  onChange,
}: {
  id?: string;
  campuses: Campus[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <Select id={id} value={value ?? ''} onChange={(e) => onChange(Number(e.target.value))} className="sm:w-64">
      {campuses.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </Select>
  );
}

export function LanguageSelect({
  id,
  languages,
  value,
  onChange,
  only,
}: {
  id?: string;
  languages: Language[];
  value: string;
  onChange: (code: string) => void;
  only?: string[];
}) {
  const list = only ? languages.filter((l) => only.includes(l.code)) : languages;
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {!list.some((l) => l.code === value) && <option value={value}>{value}</option>}
      {list.map((l) => (
        <option key={l.code} value={l.code}>
          {l.name_en} ({l.code}){l.enabled ? '' : ' — disabled'}
        </option>
      ))}
    </Select>
  );
}

/** Checkbox grid for choosing several languages. */
export function LanguageChecklist({
  languages,
  value,
  onChange,
  locked = [],
}: {
  languages: Language[];
  value: string[];
  onChange: (codes: string[]) => void;
  locked?: string[];
}) {
  return (
    <div className="grid max-h-56 grid-cols-1 gap-1.5 overflow-y-auto rounded-md border border-gray-200 p-2 sm:grid-cols-2">
      {languages.map((l) => {
        const isLocked = locked.includes(l.code);
        return (
          <Checkbox
            key={l.code}
            checked={value.includes(l.code) || isLocked}
            disabled={isLocked}
            onChange={(on) => onChange(on ? [...value, l.code] : value.filter((c) => c !== l.code))}
            label={
              <span>
                {l.name_en} <span className="text-gray-400">({l.code})</span>
                {!l.enabled && <span className="ml-1 text-xs text-amber-600">disabled</span>}
              </span>
            }
          />
        );
      })}
    </div>
  );
}
