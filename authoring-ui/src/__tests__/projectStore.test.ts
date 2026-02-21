import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  generateProjectId,
  PROJECTS_INDEX_KEY,
  projectRecipeKey,
  projectChatKey,
  LEGACY_CHAT_KEY,
  type ProjectIndex,
} from '../store/projectTypes.ts';
import { useProjectStore } from '../store/projectStore.ts';
import { useRecipeStore } from '../store/recipeStore.ts';

const TEST_CHAT_DATA = JSON.stringify([
  { role: 'user', content: '뉴스 요약해줘', timestamp: 1000 },
  {
    role: 'assistant',
    content:
      "[속보] '국가대표 AI' 패자부활전, 모티프테크놀로지스 선발 - https://n.news.naver.com/mnews/article/005/0001832991 - 국가대표 인공지능(AI) 모델 개발을 지원하기 위해 정부가 추진하는 독파모 프로젝트 패자부활전에서 스타트업 모티프테크놀로지스가 선발됐다.\n\n로블록스, 12·3 계엄 왜곡 게임 삭제 - https://n.news.naver.com/mnews/article/422/0000835674 - 12·3 계엄을 왜곡한다는 논란이 일었던 로블록스 내 게임이 규정 위반을 이유로 삭제됐다.\n\n미 빅테크들 AI 칩 자립 나선 지 오래지만... 결국 다시 엔비디아 - https://n.news.naver.com/mnews/article/469/0000915440",
    timestamp: 2000,
  },
]);

// ──────────────────────────────────────
// projectTypes.ts
// ──────────────────────────────────────
describe('projectTypes', () => {
  it('generateProjectId returns unique IDs with "proj-" prefix', () => {
    const id1 = generateProjectId();
    const id2 = generateProjectId();
    expect(id1).toMatch(/^proj-\d+-[a-z0-9]{5}$/);
    expect(id2).toMatch(/^proj-\d+-[a-z0-9]{5}$/);
    expect(id1).not.toBe(id2);
  });

  it('PROJECTS_INDEX_KEY is "wa-projects-index"', () => {
    expect(PROJECTS_INDEX_KEY).toBe('wa-projects-index');
  });

  it('projectRecipeKey(id) returns "wa-project-{id}-recipe"', () => {
    expect(projectRecipeKey('abc')).toBe('wa-project-abc-recipe');
    expect(projectRecipeKey('proj-123')).toBe('wa-project-proj-123-recipe');
  });

  it('projectChatKey(id) returns "wa-project-{id}-chat"', () => {
    expect(projectChatKey('abc')).toBe('wa-project-abc-chat');
    expect(projectChatKey('proj-123')).toBe('wa-project-proj-123-chat');
  });
});

// ──────────────────────────────────────
// projectStore.ts
// ──────────────────────────────────────
describe('projectStore', () => {
  beforeEach(() => {
    // Reset stores to initial state
    localStorage.clear();
    useRecipeStore.getState().resetToDefault();
    // Reset projectStore state directly (zustand allows setState)
    useProjectStore.setState({
      activeProjectId: '',
      projects: [],
      initialized: false,
    });
  });

  // ── initialize ──

  describe('initialize()', () => {
    it('creates a default project when no index exists', () => {
      useProjectStore.getState().initialize();

      const state = useProjectStore.getState();
      expect(state.initialized).toBe(true);
      expect(state.projects).toHaveLength(1);
      expect(state.projects[0].name).toBe('My Project');
      expect(state.projects[0].id).toMatch(/^proj-/);
      expect(state.activeProjectId).toBe(state.projects[0].id);

      // Index should be persisted
      const raw = localStorage.getItem(PROJECTS_INDEX_KEY);
      expect(raw).toBeTruthy();
      const index: ProjectIndex = JSON.parse(raw!);
      expect(index.version).toBe(1);
      expect(index.projects).toHaveLength(1);
      expect(index.activeProjectId).toBe(state.activeProjectId);
    });

    it('restores from a saved index', () => {
      const projectId = 'proj-saved-123';
      const index: ProjectIndex = {
        version: 1,
        activeProjectId: projectId,
        projects: [
          { id: projectId, name: 'Saved Project', createdAt: 1000, updatedAt: 2000 },
        ],
      };
      localStorage.setItem(PROJECTS_INDEX_KEY, JSON.stringify(index));

      // Also store a recipe for the active project
      const snap = useRecipeStore.getState().getSnapshot();
      snap.domain = 'saved.example.com';
      localStorage.setItem(projectRecipeKey(projectId), JSON.stringify(snap));

      useProjectStore.getState().initialize();

      const state = useProjectStore.getState();
      expect(state.initialized).toBe(true);
      expect(state.activeProjectId).toBe(projectId);
      expect(state.projects).toHaveLength(1);
      expect(state.projects[0].name).toBe('Saved Project');

      // Recipe should have been loaded
      expect(useRecipeStore.getState().domain).toBe('saved.example.com');
    });

    it('migrates legacy "ai-chat-history" key on first init', () => {
      localStorage.setItem(LEGACY_CHAT_KEY, TEST_CHAT_DATA);

      useProjectStore.getState().initialize();

      const state = useProjectStore.getState();
      // Legacy key should be removed
      expect(localStorage.getItem(LEGACY_CHAT_KEY)).toBeNull();

      // Chat should be migrated to the new project key
      const chatRaw = localStorage.getItem(projectChatKey(state.activeProjectId));
      expect(chatRaw).toBe(TEST_CHAT_DATA);
    });

    it('does not re-initialize if already initialized', () => {
      useProjectStore.getState().initialize();
      const firstId = useProjectStore.getState().activeProjectId;

      // Call initialize again — should be a no-op
      useProjectStore.getState().initialize();
      expect(useProjectStore.getState().activeProjectId).toBe(firstId);
      expect(useProjectStore.getState().projects).toHaveLength(1);
    });
  });

  // ── createProject ──

  describe('createProject()', () => {
    it('creates a new project and switches to it', () => {
      useProjectStore.getState().initialize();
      const oldId = useProjectStore.getState().activeProjectId;

      useProjectStore.getState().createProject('Test Project');

      const state = useProjectStore.getState();
      expect(state.projects).toHaveLength(2);
      expect(state.activeProjectId).not.toBe(oldId);

      const newProject = state.projects.find((p) => p.id === state.activeProjectId)!;
      expect(newProject.name).toBe('Test Project');
      expect(newProject.id).toMatch(/^proj-/);

      // New project should have an empty chat
      const chatRaw = localStorage.getItem(projectChatKey(state.activeProjectId));
      expect(chatRaw).toBe(JSON.stringify([]));

      // Recipe should have been reset to default
      const recipe = useRecipeStore.getState();
      expect(recipe.domain).toBe('example.com');
      expect(recipe.workflow.id).toBe('new-workflow');
    });

    it('saves the current project before creating a new one', () => {
      useProjectStore.getState().initialize();
      const oldId = useProjectStore.getState().activeProjectId;

      // Modify recipe
      useRecipeStore.getState().setActions({
        test_action: {
          instruction: 'Test',
          preferred: { selector: '#test', description: 'test', method: 'click', arguments: null },
          observedAt: '2026-01-01',
        },
      });

      useProjectStore.getState().createProject('New One');

      // The old project should have been saved with the modified recipe
      const savedRaw = localStorage.getItem(projectRecipeKey(oldId));
      expect(savedRaw).toBeTruthy();
      const savedSnap = JSON.parse(savedRaw!);
      expect(savedSnap.actions).toHaveProperty('test_action');
    });
  });

  // ── switchProject ──

  describe('switchProject()', () => {
    it('saves current project and loads target project', () => {
      useProjectStore.getState().initialize();
      const firstId = useProjectStore.getState().activeProjectId;

      // Modify current recipe
      useRecipeStore.getState().setActions({
        project1_action: {
          instruction: 'P1',
          preferred: { selector: '#p1', description: 'p1', method: 'click', arguments: null },
          observedAt: '2026-01-01',
        },
      });

      // Create second project
      useProjectStore.getState().createProject('Project 2');
      const secondId = useProjectStore.getState().activeProjectId;

      // Modify second project recipe
      useRecipeStore.getState().setActions({
        project2_action: {
          instruction: 'P2',
          preferred: { selector: '#p2', description: 'p2', method: 'click', arguments: null },
          observedAt: '2026-01-01',
        },
      });

      // Switch back to first project
      useProjectStore.getState().switchProject(firstId);

      expect(useProjectStore.getState().activeProjectId).toBe(firstId);
      // First project's recipe should be restored
      expect(useRecipeStore.getState().actions).toHaveProperty('project1_action');
      expect(useRecipeStore.getState().actions).not.toHaveProperty('project2_action');

      // Switch back to second
      useProjectStore.getState().switchProject(secondId);
      expect(useRecipeStore.getState().actions).toHaveProperty('project2_action');
    });

    it('is a no-op when switching to the active project', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;
      const saveSpy = vi.spyOn(useProjectStore.getState(), 'saveCurrentProject');
      useProjectStore.getState().switchProject(id);
      expect(saveSpy).not.toHaveBeenCalled();
      saveSpy.mockRestore();
    });

    it('is a no-op when the target project does not exist', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;
      useProjectStore.getState().switchProject('nonexistent-id');
      expect(useProjectStore.getState().activeProjectId).toBe(id);
    });

    it('resets recipe to default when target has no saved recipe', () => {
      useProjectStore.getState().initialize();
      const firstId = useProjectStore.getState().activeProjectId;

      useProjectStore.getState().createProject('Empty Project');
      const emptyId = useProjectStore.getState().activeProjectId;

      // Remove the saved recipe for the empty project
      localStorage.removeItem(projectRecipeKey(emptyId));

      // Switch to first then back to empty
      useProjectStore.getState().switchProject(firstId);
      useProjectStore.getState().switchProject(emptyId);

      // Should have been reset to defaults
      expect(useRecipeStore.getState().workflow.id).toBe('new-workflow');
    });
  });

  // ── deleteProject ──

  describe('deleteProject()', () => {
    it('removes the project and switches to another when deleting the active project', () => {
      useProjectStore.getState().initialize();
      useProjectStore.getState().createProject('Project 2');

      const proj2Id = useProjectStore.getState().activeProjectId;
      const proj1Id = useProjectStore.getState().projects.find((p) => p.id !== proj2Id)!.id;

      // Delete active project (Project 2)
      useProjectStore.getState().deleteProject(proj2Id);

      const state = useProjectStore.getState();
      expect(state.projects).toHaveLength(1);
      expect(state.projects[0].id).toBe(proj1Id);
      expect(state.activeProjectId).toBe(proj1Id);

      // localStorage should be cleaned up
      expect(localStorage.getItem(projectRecipeKey(proj2Id))).toBeNull();
      expect(localStorage.getItem(projectChatKey(proj2Id))).toBeNull();
    });

    it('removes a non-active project without switching', () => {
      useProjectStore.getState().initialize();
      const firstId = useProjectStore.getState().activeProjectId;
      useProjectStore.getState().createProject('Project 2');
      const secondId = useProjectStore.getState().activeProjectId;

      // Delete the non-active (first) project
      useProjectStore.getState().deleteProject(firstId);

      expect(useProjectStore.getState().projects).toHaveLength(1);
      expect(useProjectStore.getState().activeProjectId).toBe(secondId);
    });

    it('creates a new project first when deleting the last project', () => {
      useProjectStore.getState().initialize();
      const onlyId = useProjectStore.getState().activeProjectId;

      useProjectStore.getState().deleteProject(onlyId);

      const state = useProjectStore.getState();
      // Should still have exactly one project (the newly created one)
      expect(state.projects).toHaveLength(1);
      expect(state.projects[0].id).not.toBe(onlyId);
      expect(state.projects[0].name).toBe('My Project');
      expect(state.activeProjectId).toBe(state.projects[0].id);

      // Old project's storage should be cleaned
      expect(localStorage.getItem(projectRecipeKey(onlyId))).toBeNull();
      expect(localStorage.getItem(projectChatKey(onlyId))).toBeNull();
    });
  });

  // ── renameProject ──

  describe('renameProject()', () => {
    it('updates the project name', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;

      useProjectStore.getState().renameProject(id, 'Renamed Project');

      const project = useProjectStore.getState().projects.find((p) => p.id === id)!;
      expect(project.name).toBe('Renamed Project');

      // Check it's persisted in the index
      const raw = localStorage.getItem(PROJECTS_INDEX_KEY);
      const index: ProjectIndex = JSON.parse(raw!);
      expect(index.projects[0].name).toBe('Renamed Project');
    });

    it('updates the updatedAt timestamp', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;
      const before = useProjectStore.getState().projects[0].updatedAt;

      // Small delay to ensure timestamp difference
      vi.spyOn(Date, 'now').mockReturnValue(before + 5000);

      useProjectStore.getState().renameProject(id, 'New Name');

      const after = useProjectStore.getState().projects.find((p) => p.id === id)!.updatedAt;
      expect(after).toBeGreaterThan(before);
      vi.restoreAllMocks();
    });
  });

  // ── saveCurrentProject ──

  describe('saveCurrentProject()', () => {
    it('persists recipe to localStorage', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;

      // Modify recipe
      useRecipeStore.getState().setActions({
        saved_action: {
          instruction: 'Saved',
          preferred: { selector: '#saved', description: 'saved', method: 'click', arguments: null },
          observedAt: '2026-01-01',
        },
      });

      useProjectStore.getState().saveCurrentProject();

      const raw = localStorage.getItem(projectRecipeKey(id));
      expect(raw).toBeTruthy();
      const snap = JSON.parse(raw!);
      expect(snap.actions).toHaveProperty('saved_action');
    });

    it('updates the project timestamp in the index', () => {
      useProjectStore.getState().initialize();
      const id = useProjectStore.getState().activeProjectId;
      const before = useProjectStore.getState().projects[0].updatedAt;

      vi.spyOn(Date, 'now').mockReturnValue(before + 10000);

      useProjectStore.getState().saveCurrentProject();

      const after = useProjectStore.getState().projects.find((p) => p.id === id)!.updatedAt;
      expect(after).toBeGreaterThan(before);
      vi.restoreAllMocks();
    });

    it('is a no-op when there is no active project', () => {
      // Don't initialize — activeProjectId is ''
      expect(() => useProjectStore.getState().saveCurrentProject()).not.toThrow();
    });
  });
});

// ──────────────────────────────────────
// recipeStore snapshot tests
// ──────────────────────────────────────
describe('recipeStore snapshots', () => {
  beforeEach(() => {
    useRecipeStore.getState().resetToDefault();
  });

  it('getSnapshot() returns current recipe state', () => {
    useRecipeStore.getState().setActions({
      snap_action: {
        instruction: 'Snap',
        preferred: { selector: '#snap', description: 'snap', method: 'click', arguments: null },
        observedAt: '2026-01-01',
      },
    });

    const snap = useRecipeStore.getState().getSnapshot();
    expect(snap.actions).toHaveProperty('snap_action');
    expect(snap.domain).toBe('example.com');
    expect(snap.flow).toBe('default');
    expect(snap.version).toBe('v001');
    expect(snap.workflow).toBeDefined();
    expect(snap.selectors).toBeDefined();
    expect(snap.fingerprints).toBeDefined();
    expect(snap.policies).toBeDefined();
  });

  it('loadSnapshot() restores recipe state', () => {
    const original = useRecipeStore.getState().getSnapshot();

    // Modify state
    useRecipeStore.getState().setActions({
      modified_action: {
        instruction: 'Modified',
        preferred: { selector: '#mod', description: 'mod', method: 'click', arguments: null },
        observedAt: '2026-01-01',
      },
    });
    expect(useRecipeStore.getState().actions).toHaveProperty('modified_action');

    // Restore from snapshot
    useRecipeStore.getState().loadSnapshot(original);

    const restored = useRecipeStore.getState();
    expect(restored.actions).not.toHaveProperty('modified_action');
    expect(restored.domain).toBe('example.com');
    expect(restored.isDirty).toBe(false);
  });

  it('loadSnapshot() with custom domain/flow/version', () => {
    const snap = useRecipeStore.getState().getSnapshot();
    snap.domain = 'custom.example.com';
    snap.flow = 'custom-flow';
    snap.version = 'v999';

    useRecipeStore.getState().loadSnapshot(snap);

    const state = useRecipeStore.getState();
    expect(state.domain).toBe('custom.example.com');
    expect(state.flow).toBe('custom-flow');
    expect(state.version).toBe('v999');
  });
});
