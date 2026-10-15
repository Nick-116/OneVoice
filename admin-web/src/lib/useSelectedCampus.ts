import { useSearchParams } from 'react-router-dom';
import type { Campus } from '../types';

/** Selected campus kept in the `?campus=` query parameter (survives reloads, shareable). */
export function useSelectedCampus(campuses: Campus[] | undefined): [Campus | null, (id: number) => void] {
  const [params, setParams] = useSearchParams();
  const id = Number(params.get('campus'));
  const selected = campuses?.find((c) => c.id === id) ?? campuses?.[0] ?? null;
  const set = (cid: number) =>
    setParams(
      (p) => {
        p.set('campus', String(cid));
        return p;
      },
      { replace: true },
    );
  return [selected, set];
}
