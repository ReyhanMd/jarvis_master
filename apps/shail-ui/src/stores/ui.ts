import { create } from 'zustand';
import type { StoredCitation } from '../api';

export type CaptureState = 'live' | 'paused' | 'unknown';

type UIState = {
  inspectorMemoryId: string | null;
  evidenceRailOpen: boolean;
  lastAnswerCitations: StoredCitation[];
  captureState: CaptureState;
  pausedConversations: string[];
  highlightEvidence: boolean;

  openInspector: (id: string) => void;
  closeInspector: () => void;
  setEvidenceRailOpen: (open: boolean) => void;
  toggleEvidenceRail: () => void;
  setLastAnswerCitations: (cites: StoredCitation[]) => void;
  setCaptureState: (s: CaptureState) => void;
  setPausedConversations: (ids: string[]) => void;
  setHighlightEvidence: (on: boolean) => void;
};

export const useUIStore = create<UIState>((set, get) => ({
  inspectorMemoryId: null,
  evidenceRailOpen: false,
  lastAnswerCitations: [],
  captureState: 'unknown',
  pausedConversations: [],
  highlightEvidence: false,

  openInspector: (id) => set({ inspectorMemoryId: id }),
  closeInspector: () => set({ inspectorMemoryId: null }),
  setEvidenceRailOpen: (open) => set({ evidenceRailOpen: open }),
  toggleEvidenceRail: () => set({ evidenceRailOpen: !get().evidenceRailOpen }),
  setLastAnswerCitations: (cites) => set({ lastAnswerCitations: cites }),
  setCaptureState: (s) => set({ captureState: s }),
  setPausedConversations: (ids) => set({ pausedConversations: ids }),
  setHighlightEvidence: (on) => set({ highlightEvidence: on }),
}));
