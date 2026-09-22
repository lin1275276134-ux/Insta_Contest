import type { components } from './types/api.generated';
export type Snapshot = components['schemas']['Snapshot'];
export type Project = components['schemas']['Project'];
export type Shot = components['schemas']['Shot'];
export type Job = components['schemas']['Job'];
export type Catalog = components['schemas']['Catalog'];
export type Evidence = components['schemas']['Evidence'];
export const prefix = '/api/v1';
export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly action?: string) { super(message); }
}
export async function api<T>(path: string, method = 'GET', body?: unknown, key = crypto.randomUUID()): Promise<T> {
  const response = await fetch(prefix + path, {method, headers: method === 'GET' ? {} : {
    'Content-Type': 'application/json', 'Idempotency-Key': key
  }, body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error?.message ?? `请求失败 (${response.status})`,
                                      result.error?.code ?? 'UNKNOWN', result.error?.action);
  return result as T;
}
export function acceptSnapshot(current: Snapshot | null, incoming: Snapshot): Snapshot {
  return current?.project_id === incoming.project_id && current.revision > incoming.revision ? current : incoming;
}
// Revision advances on every freshness change, so a write built from the snapshot on
// screen can arrive stale. Resync and replay it once; the caller re-reads the revision.
export async function withResync<T>(run: () => Promise<T>, refresh: () => Promise<void>): Promise<T> {
  try { return await run(); }
  catch (e) {
    if (!(e instanceof ApiError) || e.code !== 'STALE_REVISION') throw e;
    await refresh();
    return await run();
  }
}
export async function waitJob(id: string): Promise<Job> {
  for (let i = 0; i < 120; i++) {
    const job = await api<Job>(`/jobs/${id}`);
    if (job.state === 'succeeded') return job;
    if (job.state === 'failed' || job.state === 'cancelled') throw new Error(job.error?.message ?? '任务失败');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('任务仍在后台执行，请查看任务状态');
}
