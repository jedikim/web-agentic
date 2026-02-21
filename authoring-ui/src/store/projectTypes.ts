import type { Workflow, ActionsMap, SelectorsMap, FingerprintsMap, PoliciesMap } from '../validation/schemas.ts';

export interface ProjectMeta {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
}

export interface ProjectIndex {
  version: 1;
  activeProjectId: string;
  projects: ProjectMeta[];
}

export interface RecipeSnapshot {
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  fingerprints: FingerprintsMap;
  policies: PoliciesMap;
  domain: string;
  flow: string;
  version: string;
}

// localStorage key helpers
export const PROJECTS_INDEX_KEY = 'wa-projects-index';
export const projectRecipeKey = (id: string) => `wa-project-${id}-recipe`;
export const projectChatKey = (id: string) => `wa-project-${id}-chat`;
export const LEGACY_CHAT_KEY = 'ai-chat-history';

export function generateProjectId(): string {
  return `proj-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}
