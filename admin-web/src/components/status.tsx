import type { CaptionState, OccurrenceKind, Phase, SttState } from '../types';
import { Badge, type Tone } from './ui';

const PHASES: Record<Phase, [string, Tone]> = {
  live: ['Live', 'green'],
  upcoming: ['Upcoming', 'blue'],
  ended: ['Ended', 'gray'],
  idle: ['Idle', 'gray'],
};

export function PhaseBadge({ phase }: { phase: Phase | null | undefined }) {
  if (!phase) return <Badge tone="gray">No status</Badge>;
  const [label, tone] = PHASES[phase] ?? [phase, 'gray'];
  return (
    <Badge tone={tone} dot>
      {label}
    </Badge>
  );
}

const CAPTIONS: Record<CaptionState, [string, Tone]> = {
  live: ['Captions live', 'green'],
  waiting: ['Waiting for speech', 'amber'],
  disconnected: ['Audio disconnected', 'red'],
  unavailable: ['STT unavailable', 'red'],
};

export function captionInfo(state: CaptionState | null | undefined): [string, Tone] {
  if (!state) return ['Not running', 'gray'];
  return CAPTIONS[state] ?? [state, 'gray'];
}

export function CaptionBadge({ state }: { state: CaptionState | null | undefined }) {
  const [label, tone] = captionInfo(state);
  return (
    <Badge tone={tone} dot>
      {label}
    </Badge>
  );
}

const STT: Record<SttState, Tone> = { idle: 'gray', connecting: 'amber', connected: 'green', error: 'red' };

export function SttBadge({ state }: { state: SttState | null | undefined }) {
  if (!state) return <Badge tone="gray">idle</Badge>;
  return <Badge tone={STT[state] ?? 'gray'}>{state}</Badge>;
}

export function translationTone(state: string): Tone {
  if (state === 'ok') return 'green';
  if (state === 'failing' || state === 'error' || state === 'unavailable') return 'red';
  if (state === 'pending' || state === 'starting' || state === 'idle') return 'gray';
  return 'amber';
}

const KINDS: Record<OccurrenceKind, Tone> = { recurring: 'gray', special: 'indigo', holiday: 'amber', manual: 'blue' };

export function KindBadge({ kind }: { kind: OccurrenceKind | string }) {
  return <Badge tone={KINDS[kind as OccurrenceKind] ?? 'gray'}>{kind}</Badge>;
}
