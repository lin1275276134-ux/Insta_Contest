import { describe, it, expect } from 'vitest';
import { acceptSnapshot, withResync, ApiError, type Snapshot } from './api';
describe('UI05 snapshot revision', () => {
  it('rejects late older snapshots but switches project', () => {
    const current = {project_id:'a', revision:10} as Snapshot;
    expect(acceptSnapshot(current, {project_id:'a',revision:9} as Snapshot)).toBe(current);
    expect(acceptSnapshot(current, {project_id:'b',revision:1} as Snapshot).project_id).toBe('b');
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
