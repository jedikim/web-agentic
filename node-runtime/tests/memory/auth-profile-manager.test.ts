import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { AuthProfileManager } from '../../src/memory/auth-profile-manager.js';
import type { AuthProfile } from '../../src/memory/auth-profile-manager.js';
import { rm, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

describe('AuthProfileManager', () => {
  let profilesDir: string;
  let manager: AuthProfileManager;

  const sampleProfile: AuthProfile = {
    id: 'user1-example',
    domain: 'example.com',
    cookies: [{ name: 'session', value: 'abc123' }],
    localStorage: { token: 'jwt-token-here' },
    savedAt: '2026-02-21T10:00:00Z',
  };

  beforeEach(async () => {
    profilesDir = join(tmpdir(), `auth-profile-test-${randomUUID()}`);
    await mkdir(profilesDir, { recursive: true });
    manager = new AuthProfileManager(profilesDir);
  });

  afterEach(async () => {
    await rm(profilesDir, { recursive: true, force: true });
  });

  describe('save and load', () => {
    it('saves and loads a profile', async () => {
      await manager.save(sampleProfile);
      const loaded = await manager.load('user1-example');
      expect(loaded).not.toBeNull();
      expect(loaded!.id).toBe('user1-example');
      expect(loaded!.domain).toBe('example.com');
      expect(loaded!.cookies).toEqual(sampleProfile.cookies);
      expect(loaded!.localStorage).toEqual(sampleProfile.localStorage);
    });

    it('returns null for non-existent profile', async () => {
      const loaded = await manager.load('nonexistent');
      expect(loaded).toBeNull();
    });

    it('overwrites existing profile on save', async () => {
      await manager.save(sampleProfile);
      const updated = { ...sampleProfile, localStorage: { token: 'new-token' } };
      await manager.save(updated);

      const loaded = await manager.load('user1-example');
      expect(loaded!.localStorage).toEqual({ token: 'new-token' });
    });
  });

  describe('delete', () => {
    it('deletes an existing profile', async () => {
      await manager.save(sampleProfile);
      const deleted = await manager.delete('user1-example');
      expect(deleted).toBe(true);

      const loaded = await manager.load('user1-example');
      expect(loaded).toBeNull();
    });

    it('returns false when deleting non-existent profile', async () => {
      const deleted = await manager.delete('nonexistent');
      expect(deleted).toBe(false);
    });
  });

  describe('list', () => {
    it('lists all profile IDs', async () => {
      await manager.save(sampleProfile);
      await manager.save({ ...sampleProfile, id: 'user2-example' });

      const ids = await manager.list();
      expect(ids.sort()).toEqual(['user1-example', 'user2-example']);
    });

    it('returns empty array when no profiles exist', async () => {
      const ids = await manager.list();
      expect(ids).toEqual([]);
    });
  });
});
