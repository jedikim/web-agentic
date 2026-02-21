import JSZip from 'jszip';

export interface RecipeFiles {
  workflow: unknown;
  actions: unknown;
  selectors: unknown;
  fingerprints: unknown;
  policies: unknown;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function exportJsonFile(data: unknown, filename: string) {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  triggerDownload(blob, filename);
}

export async function exportRecipeZip(
  recipe: RecipeFiles,
  domain: string,
  version: string,
): Promise<void> {
  const zip = new JSZip();
  const folder = zip.folder(`${domain}-${version}`)!;
  folder.file('workflow.json', JSON.stringify(recipe.workflow, null, 2));
  folder.file('actions.json', JSON.stringify(recipe.actions, null, 2));
  folder.file('selectors.json', JSON.stringify(recipe.selectors, null, 2));
  folder.file('fingerprints.json', JSON.stringify(recipe.fingerprints, null, 2));
  folder.file('policies.json', JSON.stringify(recipe.policies, null, 2));

  const blob = await zip.generateAsync({ type: 'blob' });
  triggerDownload(blob, `recipe-${domain}-${version}.zip`);
}

export async function exportRecipeZipAsBlob(
  recipe: RecipeFiles,
  domain: string,
  version: string,
): Promise<Blob> {
  const zip = new JSZip();
  const folder = zip.folder(`${domain}-${version}`)!;
  folder.file('workflow.json', JSON.stringify(recipe.workflow, null, 2));
  folder.file('actions.json', JSON.stringify(recipe.actions, null, 2));
  folder.file('selectors.json', JSON.stringify(recipe.selectors, null, 2));
  folder.file('fingerprints.json', JSON.stringify(recipe.fingerprints, null, 2));
  folder.file('policies.json', JSON.stringify(recipe.policies, null, 2));

  return zip.generateAsync({ type: 'blob' });
}
