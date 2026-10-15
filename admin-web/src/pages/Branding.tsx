import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';
import { api } from '../api';
import { Badge, Button, Card, ConfirmDialog, ErrorBox, Field, Input, Loading, PageHeader } from '../components/ui';
import { useToast } from '../components/Toast';
import { keys, useAction } from '../lib/queries';
import type { Branding } from '../types';

const brandingKey = ['branding'] as const;
const HEX = /^#[0-9a-fA-F]{6}$/;
const MAX_LOGO_BYTES = 5 * 1024 * 1024;
const PRESETS = ['#F37121', '#2563EB', '#16A34A', '#7C3AED', '#DC2626', '#0D9488', '#111827'];

/** Phone-sized preview drawn as SVG (colors via attributes, so it works under the strict CSP). */
function Preview({ branding, accent, name, logoSrc }: { branding: Branding; accent: string; name: string; logoSrc: string | null }) {
  const p = accent.toUpperCase() === branding.accent_color.toUpperCase() ? branding.palette : null;
  const fill = p ? p['700'] : accent;
  const tint = p ? p['50'] : '#F3F4F6';
  const border = p ? p['600'] : accent;
  return (
    <svg viewBox="0 0 240 300" className="mx-auto h-72 w-auto rounded-2xl border border-gray-200 bg-white shadow-sm" role="img" aria-label="Preview of the caption site">
      {logoSrc ? <image href={logoSrc} x="90" y="18" width="60" height="48" preserveAspectRatio="xMidYMid meet" /> : null}
      <text x="120" y="88" textAnchor="middle" fontSize="15" fontWeight="600" fill="#111827">{name || 'Church name'}</text>
      <text x="120" y="118" textAnchor="middle" fontSize="16" fontWeight="700" fill="#111827">Welcome</text>
      <rect x="20" y="136" width="200" height="34" rx="10" fill="white" stroke="#E5E7EB" strokeWidth="2" />
      <text x="34" y="158" fontSize="12" fill="#111827">English</text>
      <rect x="20" y="178" width="200" height="34" rx="10" fill={tint} stroke={border} strokeWidth="2" />
      <text x="34" y="200" fontSize="12" fill="#111827">Español</text>
      <circle cx="204" cy="195" r="6" fill="white" stroke={border} strokeWidth="2" />
      <circle cx="204" cy="195" r="3" fill={border} />
      <rect x="20" y="240" width="200" height="38" rx="12" fill={fill} />
      <text x="120" y="264" textAnchor="middle" fontSize="13" fontWeight="600" fill="white">Continue</text>
    </svg>
  );
}

function BrandingForm({ branding }: { branding: Branding }) {
  const toast = useToast();
  const [name, setName] = useState(branding.church_name);
  const [accent, setAccent] = useState(branding.accent_color);
  const [removeOpen, setRemoveOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const logoSrc = branding.logo ? `/api/branding/logo?v=${branding.logo.sha256.slice(0, 16)}` : null;

  const save = useAction((b: { church_name?: string; accent_color?: string }) => api.put<Branding>('/api/branding', b), {
    success: 'Branding saved. Phones pick it up within a minute.',
    invalidate: [brandingKey, keys.settings],
  });
  const upload = useAction((file: File) => api.upload<Branding>('/api/branding/logo', file), {
    success: 'Logo uploaded',
    invalidate: [brandingKey],
  });
  const remove = useAction(() => api.del<Branding>('/api/branding/logo'), {
    success: 'Logo removed',
    invalidate: [brandingKey],
    onSuccess: () => setRemoveOpen(false),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const changes: { church_name?: string; accent_color?: string } = {};
    if (name.trim() && name.trim() !== branding.church_name) changes.church_name = name.trim();
    if (HEX.test(accent) && accent.toUpperCase() !== branding.accent_color.toUpperCase()) changes.accent_color = accent.toUpperCase();
    if (Object.keys(changes).length) save.mutate(changes);
  }

  function pickFile(file: File | undefined) {
    if (!file) return;
    if (file.type !== 'image/png') {
      toast.error('Please choose a PNG file.');
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      toast.error('The logo must be 5 MB or smaller.');
      return;
    }
    upload.mutate(file);
    if (fileRef.current) fileRef.current.value = '';
  }

  const contrast = branding.contrast['700'];
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_auto]">
      <div className="space-y-5">
        <Card title="Name and colors">
          <form onSubmit={submit} className="space-y-4">
            <Field label="Church name" hint="Shown under the logo on the caption site.">
              {(id) => <Input id={id} maxLength={120} required value={name} onChange={(e) => setName(e.target.value)} />}
            </Field>
            <Field
              label="Button color"
              hint="Used for buttons, the selected language and links. Darker shades are calculated automatically so text stays readable."
            >
              {(id) => (
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    type="color"
                    aria-label="Pick a color"
                    value={HEX.test(accent) ? accent : '#000000'}
                    onChange={(e) => setAccent(e.target.value.toUpperCase())}
                    className="h-10 w-14 cursor-pointer rounded border border-gray-300 bg-white p-1"
                  />
                  <Input
                    id={id}
                    className="w-32 font-mono uppercase"
                    maxLength={7}
                    value={accent}
                    onChange={(e) => setAccent(e.target.value.startsWith('#') ? e.target.value : `#${e.target.value}`)}
                    aria-invalid={!HEX.test(accent)}
                  />
                  <div className="flex gap-1.5" aria-label="Presets">
                    {PRESETS.map((c) => (
                      <button
                        key={c}
                        type="button"
                        title={c}
                        onClick={() => setAccent(c)}
                        className="h-7 w-7 rounded-full border border-gray-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
                      >
                        <svg viewBox="0 0 10 10" className="h-full w-full" aria-hidden="true">
                          <circle cx="5" cy="5" r="5" fill={c} />
                        </svg>
                        <span className="sr-only">Use {c}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </Field>
            {!HEX.test(accent) && <p className="text-sm text-red-700">Enter a color like #F37121.</p>}
            {contrast !== undefined && (
              <p className="text-xs text-gray-500">
                Saved color: buttons use {branding.palette['700']} with white text (contrast {contrast}:1
                {contrast >= 4.5 ? ', meets WCAG AA' : ''}).
              </p>
            )}
            <div className="flex justify-end">
              <Button type="submit" variant="primary" loading={save.isPending} disabled={!HEX.test(accent) || !name.trim()}>
                Save name and color
              </Button>
            </div>
          </form>
        </Card>

        <Card title="Logo">
          <div className="flex flex-wrap items-center gap-5">
            <div className="flex h-24 w-40 items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50">
              {logoSrc ? <img src={logoSrc} alt="Current logo" className="max-h-20 max-w-36 object-contain" /> : <span className="text-sm text-gray-500">No logo</span>}
            </div>
            <div className="space-y-2">
              <input ref={fileRef} type="file" accept="image/png" className="sr-only" id="logo-file" onChange={(e) => pickFile(e.target.files?.[0])} />
              <div className="flex gap-2">
                <Button variant="primary" loading={upload.isPending} onClick={() => fileRef.current?.click()}>
                  {branding.logo ? 'Replace logo' : 'Upload logo'}
                </Button>
                {branding.logo && (
                  <Button variant="danger" onClick={() => setRemoveOpen(true)}>
                    Remove
                  </Button>
                )}
              </div>
              <p className="text-xs text-gray-500">
                PNG only, up to 5 MB. A transparent background works best. Large images are resized to 1024 px.
              </p>
              {branding.logo && <Badge tone="green">Uploaded</Badge>}
            </div>
          </div>
        </Card>
      </div>

      <Card title="Preview">
        <Preview branding={branding} accent={HEX.test(accent) ? accent : branding.accent_color} name={name} logoSrc={logoSrc} />
        <p className="mt-2 max-w-60 text-center text-xs text-gray-500">The preview shows exact shades after you save.</p>
      </Card>

      <ConfirmDialog
        open={removeOpen}
        title="Remove logo?"
        message="The caption site will show the church name without a logo."
        confirmLabel="Remove logo"
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setRemoveOpen(false)}
      />
    </div>
  );
}

export function BrandingPage() {
  const q = useQuery({ queryKey: brandingKey, queryFn: () => api.get<Branding>('/api/branding') });
  return (
    <div className="space-y-5">
      <PageHeader title="Branding" description="How the public caption site looks to your congregation." />
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : <BrandingForm key={JSON.stringify(q.data)} branding={q.data} />}
    </div>
  );
}
