import { describe, it, expect } from 'vitest';
import { detectFileType } from '../utils/importRecipe.ts';
import { exportRecipeZipAsBlob } from '../utils/exportRecipe.ts';
import { importFromZipBuffer } from '../utils/importRecipe.ts';
import { createDefaultRecipe } from '../utils/recipeDefaults.ts';

describe('detectFileType', () => {
  it('detects workflow by steps array', () => {
    expect(detectFileType({ id: 'wf', steps: [{ id: 's1', op: 'goto' }] })).toBe('workflow');
  });

  it('detects actions by instruction field', () => {
    expect(
      detectFileType({
        click: { instruction: 'Click it', preferred: {}, observedAt: '' },
      }),
    ).toBe('actions');
  });

  it('detects selectors by primary + fallbacks', () => {
    expect(
      detectFileType({
        btn: { primary: '#btn', fallbacks: ['.btn'], strategy: 'css' },
      }),
    ).toBe('selectors');
  });

  it('detects fingerprints by mustText/urlContains', () => {
    expect(
      detectFileType({
        page: { mustText: ['Hello'], urlContains: 'example.com' },
      }),
    ).toBe('fingerprints');
  });

  it('detects policies by hard + score', () => {
    expect(
      detectFileType({
        default: { hard: [], score: [], tie_break: [], pick: 'first' },
      }),
    ).toBe('policies');
  });

  it('defaults to policies for empty object', () => {
    expect(detectFileType({})).toBe('policies');
  });
});

describe('ZIP round-trip', () => {
  it('exports and re-imports a recipe via ZIP', async () => {
    const recipe = createDefaultRecipe();
    recipe.workflow.steps = [
      { id: 'step-1', op: 'goto', args: { url: 'https://example.com' } },
      { id: 'step-2', op: 'act_cached', targetKey: 'login_btn' },
    ];
    recipe.actions = {
      login_btn: {
        instruction: 'Click login',
        preferred: { selector: '#login', description: 'Login button', method: 'click' },
        observedAt: '2026-01-01',
      },
    };

    const blob = await exportRecipeZipAsBlob(recipe, 'test.com', 'v001');
    const buffer = await blob.arrayBuffer();
    const imported = await importFromZipBuffer(buffer);

    expect(imported.workflow).toBeDefined();
    expect(imported.actions).toBeDefined();
    expect(imported.selectors).toBeDefined();
    expect(imported.fingerprints).toBeDefined();
    expect(imported.policies).toBeDefined();

    const wf = imported.workflow as { steps: Array<{ id: string }> };
    expect(wf.steps).toHaveLength(2);
    expect(wf.steps[0].id).toBe('step-1');
  });
});
