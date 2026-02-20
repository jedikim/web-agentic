import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { Recipe } from '../types/index.js';

export function nextVersion(current: string): string {
  const num = parseInt(current.slice(1), 10);
  return `v${String(num + 1).padStart(3, '0')}`;
}

export async function saveRecipeVersion(basePath: string, recipe: Recipe): Promise<string> {
  const newVersion = nextVersion(recipe.version);
  const versionDir = join(basePath, newVersion);

  await mkdir(versionDir, { recursive: true });

  await Promise.all([
    writeFile(join(versionDir, 'workflow.json'), JSON.stringify(recipe.workflow, null, 2)),
    writeFile(join(versionDir, 'actions.json'), JSON.stringify(recipe.actions, null, 2)),
    writeFile(join(versionDir, 'selectors.json'), JSON.stringify(recipe.selectors, null, 2)),
    writeFile(join(versionDir, 'policies.json'), JSON.stringify(recipe.policies, null, 2)),
    writeFile(join(versionDir, 'fingerprints.json'), JSON.stringify(recipe.fingerprints, null, 2)),
  ]);

  return newVersion;
}
