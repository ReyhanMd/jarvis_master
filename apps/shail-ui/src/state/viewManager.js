/**
 * View State Manager
 * 
 * Manages state and transitions between the 4 views:
 * - View 1: Quick Popup
 * - View 2: Chat Overlay
 * - View 3: Agent + Software Interaction
 * - View 4: Bird's-Eye Workflow View
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const VIEWS = {
  QUICK_POPUP: 'quick_popup',
  CHAT_OVERLAY: 'chat_overlay',
  SOFTWARE_VIEW: 'software_view',
  BIRDSEYE: 'birdseye',
};

const useViewManager = create(
  persist(
    (set, get) => ({
      currentView: VIEWS.QUICK_POPUP,
      viewHistory: [],
      viewState: {
        [VIEWS.QUICK_POPUP]: {},
        [VIEWS.CHAT_OVERLAY]: {},
        [VIEWS.SOFTWARE_VIEW]: {},
        [VIEWS.BIRDSEYE]: {},
      },

      // Navigate to a view
      navigateTo: (viewName, state = {}) => {
        const current = get().currentView;
        set((prev) => ({
          currentView: viewName,
          viewHistory: [...prev.viewHistory, current],
          viewState: {
            ...prev.viewState,
            [viewName]: { ...prev.viewState[viewName], ...state },
          },
        }));
      },

      // Navigate back
      navigateBack: () => {
        const history = get().viewHistory;
        if (history.length > 0) {
          const previousView = history[history.length - 1];
          set((prev) => ({
            currentView: previousView,
            viewHistory: prev.viewHistory.slice(0, -1),
          }));
        }
      },

      // Update state for current view
      updateViewState: (updates) => {
        set((prev) => ({
          viewState: {
            ...prev.viewState,
            [prev.currentView]: {
              ...prev.viewState[prev.currentView],
              ...updates,
            },
          },
        }));
      },

      // Get state for a view
      getViewState: (viewName) => {
        return get().viewState[viewName] || {};
      },

      // Reset view state
      resetView: (viewName) => {
        set((prev) => ({
          viewState: {
            ...prev.viewState,
            [viewName]: {},
          },
        }));
      },
    }),
    {
      name: 'shail-view-state',
    }
  )
);

export { VIEWS, useViewManager };
