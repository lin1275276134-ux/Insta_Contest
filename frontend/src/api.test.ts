import { describe, it, expect } from 'vitest';
import { acceptSnapshot, withResync, ApiError, requestKey, uploadLocalFiles, type Snapshot } from './api';
describe('UI05 snapshot revision', () => {
  it('rejects late older snapshots but switches project', () => {
    const current = {project_id:'a', revision:10} as Snapshot;
    expect(acceptSnapshot(current, {project_id:'a',revision:9} as Snapshot)).toBe(current);
    expect(acceptSnapshot(current, {project_id:'b',revision:1} as Snapshot).project_id).toBe('b');
  });
});
describe('local material upload', () => {
  it('creates a valid fallback idempotency key', () => {
    expect(requestKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
  it('encodes the project id and sends multipart fields', async () => {
    const originalFetch = globalThis.fetch;
    let seenUrl = '', seenBody: FormData | undefined;
    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      seenUrl = String(url); seenBody = init?.body as FormData;
      return new Response(JSON.stringify({items: []}), {status: 202, headers: {'Content-Type':'application/json'}});
    }) as typeof fetch;
    try {
      await uploadLocalFiles('project/a b', 7, [new File(['video'], '素材 01.mp4', {type:'video/mp4'})]);
      expect(seenUrl).toBe('/api/v1/projects/project%2Fa%20b/imports');
      expect(seenBody?.get('expected_revision')).toBe('7');
      expect(seenBody?.get('projection')).toBe('rectilinear');
      expect((seenBody?.get('files') as File).name).toBe('素材 01.mp4');
    } finally { globalThis.fetch = originalFetch; }
  });
});
describe('UI06 resync on stale revision', () => {
  it('refreshes before replaying so the retry sends the newer revision', async () => {
    const seen: number[] = [];
    let revision = 7;
    const result = await withResync(async () => {
      seen.push(revision);
      if (seen.length === 1) throw new ApiError('页面已更新', 'STALE_REVISION', 'refresh');
      return revision;
    }, async () => { revision = 9; });
    expect(result).toBe(9);
    expect(seen).toEqual([7, 9]);
  });
  it('replays an action only for STALE_REVISION', async () => {
    let calls = 0, refreshes = 0;
    await expect(withResync(async () => { calls++; throw new ApiError('清单已锁定', 'CONFLICT'); },
                            async () => { refreshes++; })).rejects.toThrow('清单已锁定');
    expect([calls, refreshes]).toEqual([1, 0]);
  });
  it('gives up after one retry and surfaces the conflict', async () => {
    let calls = 0, refreshes = 0;
    await expect(withResync(async () => { calls++; throw new ApiError('页面已更新', 'STALE_REVISION'); },
                            async () => { refreshes++; })).rejects.toThrow('页面已更新');
    expect([calls, refreshes]).toEqual([2, 1]);
  });
});
