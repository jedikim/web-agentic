import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';

export interface AuthProfile {
  id: string;
  domain: string;
  cookies?: Record<string, string>[];
  localStorage?: Record<string, string>;
  sessionStorage?: Record<string, string>;
  savedAt: string;
}

/**
 * Manage browser auth state (cookies/storage) profiles.
 * Stores profiles as JSON files for session reuse across runs.
 */
export class AuthProfileManager {
  constructor(private profilesDir: string) {}

  /**
   * Load a saved auth profile by ID.
   */
  async load(profileId: string): Promise<AuthProfile | null> {
    const filePath = join(this.profilesDir, `${profileId}.json`);
    try {
      const data = await readFile(filePath, 'utf-8');
      return JSON.parse(data) as AuthProfile;
    } catch {
      return null;
    }
  }

  /**
   * Save an auth profile.
   */
  async save(profile: AuthProfile): Promise<void> {
    await mkdir(this.profilesDir, { recursive: true });
    const filePath = join(this.profilesDir, `${profile.id}.json`);
    const toSave: AuthProfile = {
      ...profile,
      savedAt: new Date().toISOString(),
    };
    await writeFile(filePath, JSON.stringify(toSave, null, 2), 'utf-8');
  }

  /**
   * Delete an auth profile.
   */
  async delete(profileId: string): Promise<boolean> {
    const filePath = join(this.profilesDir, `${profileId}.json`);
    try {
      const { unlink } = await import('node:fs/promises');
      await unlink(filePath);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * List all stored profile IDs.
   */
  async list(): Promise<string[]> {
    try {
      const { readdir } = await import('node:fs/promises');
      const files = await readdir(this.profilesDir);
      return files
        .filter((f) => f.endsWith('.json'))
        .map((f) => f.replace('.json', ''));
    } catch {
      return [];
    }
  }
}
