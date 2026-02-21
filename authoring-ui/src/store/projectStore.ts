import { create } from 'zustand';
import { useRecipeStore } from './recipeStore.ts';
import {
  type ProjectMeta,
  type ProjectIndex,
  type RecipeSnapshot,
  PROJECTS_INDEX_KEY,
  projectRecipeKey,
  projectChatKey,
  LEGACY_CHAT_KEY,
  generateProjectId,
} from './projectTypes.ts';

interface ProjectState {
  activeProjectId: string;
  projects: ProjectMeta[];
  initialized: boolean;
}

interface ProjectActions {
  initialize: () => void;
  switchProject: (id: string) => void;
  createProject: (name: string) => void;
  deleteProject: (id: string) => void;
  renameProject: (id: string, name: string) => void;
  saveCurrentProject: () => void;
}

export type ProjectStore = ProjectState & ProjectActions;

function loadIndex(): ProjectIndex | null {
  try {
    const raw = localStorage.getItem(PROJECTS_INDEX_KEY);
    if (raw) return JSON.parse(raw) as ProjectIndex;
  } catch { /* ignore */ }
  return null;
}

function saveIndex(index: ProjectIndex) {
  localStorage.setItem(PROJECTS_INDEX_KEY, JSON.stringify(index));
}

function saveRecipe(projectId: string, snap: RecipeSnapshot) {
  localStorage.setItem(projectRecipeKey(projectId), JSON.stringify(snap));
}

function loadRecipe(projectId: string): RecipeSnapshot | null {
  try {
    const raw = localStorage.getItem(projectRecipeKey(projectId));
    if (raw) return JSON.parse(raw) as RecipeSnapshot;
  } catch { /* ignore */ }
  return null;
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  activeProjectId: '',
  projects: [],
  initialized: false,

  initialize: () => {
    if (get().initialized) return;

    const existing = loadIndex();
    if (existing && existing.projects.length > 0) {
      set({
        activeProjectId: existing.activeProjectId,
        projects: existing.projects,
        initialized: true,
      });

      const snap = loadRecipe(existing.activeProjectId);
      if (snap) {
        useRecipeStore.getState().loadSnapshot(snap);
      }
    } else {
      const id = generateProjectId();
      const now = Date.now();
      const meta: ProjectMeta = { id, name: 'My Project', createdAt: now, updatedAt: now };

      const legacyChat = localStorage.getItem(LEGACY_CHAT_KEY);
      if (legacyChat) {
        localStorage.setItem(projectChatKey(id), legacyChat);
        localStorage.removeItem(LEGACY_CHAT_KEY);
      }

      const snap = useRecipeStore.getState().getSnapshot();
      saveRecipe(id, snap);

      const index: ProjectIndex = { version: 1, activeProjectId: id, projects: [meta] };
      saveIndex(index);

      set({ activeProjectId: id, projects: [meta], initialized: true });
    }

    window.addEventListener('beforeunload', () => {
      get().saveCurrentProject();
    });
  },

  saveCurrentProject: () => {
    const { activeProjectId, projects } = get();
    if (!activeProjectId) return;

    const snap = useRecipeStore.getState().getSnapshot();
    saveRecipe(activeProjectId, snap);

    const updated = projects.map((p) =>
      p.id === activeProjectId ? { ...p, updatedAt: Date.now() } : p,
    );
    const index: ProjectIndex = { version: 1, activeProjectId, projects: updated };
    saveIndex(index);
    set({ projects: updated });
  },

  switchProject: (id: string) => {
    const { activeProjectId, projects } = get();
    if (id === activeProjectId) return;
    if (!projects.find((p) => p.id === id)) return;

    get().saveCurrentProject();

    const snap = loadRecipe(id);
    if (snap) {
      useRecipeStore.getState().loadSnapshot(snap);
    } else {
      useRecipeStore.getState().resetToDefault();
    }

    set({ activeProjectId: id });
    saveIndex({ version: 1, activeProjectId: id, projects: get().projects });
  },

  createProject: (name: string) => {
    get().saveCurrentProject();

    const id = generateProjectId();
    const now = Date.now();
    const meta: ProjectMeta = { id, name, createdAt: now, updatedAt: now };

    useRecipeStore.getState().resetToDefault();
    const snap = useRecipeStore.getState().getSnapshot();
    saveRecipe(id, snap);

    localStorage.setItem(projectChatKey(id), JSON.stringify([]));

    const projects = [...get().projects, meta];
    set({ activeProjectId: id, projects });
    saveIndex({ version: 1, activeProjectId: id, projects });
  },

  deleteProject: (id: string) => {
    const { projects, activeProjectId } = get();
    if (projects.length <= 1) {
      get().createProject('My Project');
      localStorage.removeItem(projectRecipeKey(id));
      localStorage.removeItem(projectChatKey(id));
      const filtered = get().projects.filter((p) => p.id !== id);
      set({ projects: filtered });
      saveIndex({ version: 1, activeProjectId: get().activeProjectId, projects: filtered });
      return;
    }

    localStorage.removeItem(projectRecipeKey(id));
    localStorage.removeItem(projectChatKey(id));

    const filtered = projects.filter((p) => p.id !== id);

    if (id === activeProjectId) {
      const next = filtered[0];
      const snap = loadRecipe(next.id);
      if (snap) {
        useRecipeStore.getState().loadSnapshot(snap);
      } else {
        useRecipeStore.getState().resetToDefault();
      }
      set({ activeProjectId: next.id, projects: filtered });
      saveIndex({ version: 1, activeProjectId: next.id, projects: filtered });
    } else {
      set({ projects: filtered });
      saveIndex({ version: 1, activeProjectId, projects: filtered });
    }
  },

  renameProject: (id: string, name: string) => {
    const projects = get().projects.map((p) =>
      p.id === id ? { ...p, name, updatedAt: Date.now() } : p,
    );
    set({ projects });
    saveIndex({ version: 1, activeProjectId: get().activeProjectId, projects });
  },
}));
