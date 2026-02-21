import { create } from 'zustand';

export type RecipeFileTab = 'workflow' | 'actions' | 'selectors' | 'fingerprints' | 'policies';

export interface ValidationError {
  file: RecipeFileTab;
  path: string;
  message: string;
}

interface UiState {
  selectedNodeId: string | null;
  activeTab: RecipeFileTab;
  validationErrors: ValidationError[];
  sidebarOpen: boolean;
}

interface UiActions {
  setSelectedNodeId: (id: string | null) => void;
  setActiveTab: (tab: RecipeFileTab) => void;
  setValidationErrors: (errors: ValidationError[]) => void;
  toggleSidebar: () => void;
}

export type UiStore = UiState & UiActions;

export const useUiStore = create<UiStore>((set) => ({
  selectedNodeId: null,
  activeTab: 'workflow',
  validationErrors: [],
  sidebarOpen: true,

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setValidationErrors: (errors) => set({ validationErrors: errors }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
