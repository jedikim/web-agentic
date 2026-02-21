import JSZip from 'jszip';

export type RecipeFileType = 'workflow' | 'actions' | 'selectors' | 'fingerprints' | 'policies';

export function detectFileType(data: Record<string, unknown>): RecipeFileType {
  if (Array.isArray(data.steps)) return 'workflow';
  if (typeof data === 'object' && data !== null) {
    const values = Object.values(data);
    if (values.length > 0) {
      const first = values[0] as Record<string, unknown> | undefined;
      if (first && typeof first === 'object') {
        if ('instruction' in first) return 'actions';
        if ('primary' in first && 'fallbacks' in first) return 'selectors';
        if ('mustText' in first || 'urlContains' in first || 'mustSelectors' in first) return 'fingerprints';
        if ('hard' in first && 'score' in first) return 'policies';
      }
    }
  }
  return 'policies';
}

export function detectFileTypeByName(filename: string): RecipeFileType | null {
  const lower = filename.toLowerCase();
  if (lower.includes('workflow')) return 'workflow';
  if (lower.includes('action')) return 'actions';
  if (lower.includes('selector')) return 'selectors';
  if (lower.includes('fingerprint')) return 'fingerprints';
  if (lower.includes('polic')) return 'policies';
  return null;
}

async function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

async function readFileAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
}

export async function importFromFiles(files: FileList): Promise<Record<string, unknown>> {
  const result: Record<string, unknown> = {};

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    if (file.name.endsWith('.zip')) {
      const zipResult = await importFromZipFile(file);
      Object.assign(result, zipResult);
    } else if (file.name.endsWith('.json')) {
      const text = await readFileAsText(file);
      const data = JSON.parse(text) as Record<string, unknown>;
      const type = detectFileTypeByName(file.name) ?? detectFileType(data);
      result[type] = data;
    }
  }

  return result;
}

export async function importFromZipFile(file: File): Promise<Record<string, unknown>> {
  const buffer = await readFileAsArrayBuffer(file);
  return importFromZipBuffer(buffer);
}

export async function importFromZipBuffer(buffer: ArrayBuffer): Promise<Record<string, unknown>> {
  const zip = await JSZip.loadAsync(buffer);
  const result: Record<string, unknown> = {};

  for (const [filename, zipEntry] of Object.entries(zip.files)) {
    if (zipEntry.dir || !filename.endsWith('.json')) continue;
    const text = await zipEntry.async('text');
    const data = JSON.parse(text) as Record<string, unknown>;
    const basename = filename.split('/').pop() ?? filename;
    const type = detectFileTypeByName(basename) ?? detectFileType(data);
    result[type] = data;
  }

  return result;
}
