import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { useToast } from '../components/Toast';
import type { Campus, GeneralSettings, Language, QrLink } from '../types';

export const keys = {
  overview: ['overview'] as const,
  campuses: ['campuses'] as const,
  languages: ['languages'] as const,
  settings: ['settings'] as const,
  qrLinks: ['qr-links'] as const,
};

export function useCampuses() {
  return useQuery({ queryKey: keys.campuses, queryFn: () => api.get<Campus[]>('/api/campuses') });
}

export function useLanguages() {
  return useQuery({ queryKey: keys.languages, queryFn: () => api.get<Language[]>('/api/languages') });
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: () => api.get<GeneralSettings>('/api/settings') });
}

export function useQrLinks() {
  return useQuery({ queryKey: keys.qrLinks, queryFn: () => api.get<QrLink[]>('/api/qr-links') });
}

/**
 * Mutation that shows a success toast, surfaces API `detail` errors as a toast,
 * and invalidates the given query keys afterwards.
 */
export function useAction<TVars = void, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  opts: { success?: string | ((r: TResult, v: TVars) => string); invalidate?: QueryKey[]; onSuccess?: (r: TResult, v: TVars) => void } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<TResult, Error, TVars>({
    mutationFn: fn,
    onSuccess: (r, v) => {
      if (opts.success) toast.success(typeof opts.success === 'function' ? opts.success(r, v) : opts.success);
      opts.onSuccess?.(r, v);
    },
    onError: (e) => toast.error(e),
    onSettled: () => {
      for (const k of opts.invalidate ?? []) void qc.invalidateQueries({ queryKey: k });
    },
  });
}

/** Re-render every `intervalMs` with the current time (for countdowns / relative times). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function languageName(langs: Language[] | undefined, code: string): string {
  const l = langs?.find((x) => x.code === code);
  return l ? l.name_en : code;
}
