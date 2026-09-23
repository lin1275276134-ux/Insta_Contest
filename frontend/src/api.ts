import type { components } from './types/api.generated';
export type Snapshot = components['schemas']['Snapshot'];
export type Project = components['schemas']['Project'];
export type Shot = components['schemas']['Shot'];
export type Job = components['schemas']['Job'];
export type Evidence = components['schemas']['Evidence'];
export const prefix = '/api/v1';
export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly action?: string) { super(message); }
}
export function requestKey(): string {
  // randomUUID is missing in some older WebKit builds (and is restricted to a
  // secure context outside localhost). getRandomValues has much wider support.
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export async function api<T>(path: string, method = 'GET', body?: unknown, key = requestKey()): Promise<T> {
  const response = await fetch(prefix + path, {method, headers: method === 'GET' ? {} : {
    'Content-Type': 'application/json', 'Idempotency-Key': key
  }, body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error?.message ?? `请求失败 (${response.status})`,
                                      result.error?.code ?? 'UNKNOWN', result.error?.action);
  return result as T;
}
export async function uploadLocalFiles(projectId: string, revision: number, files: File[]): Promise<unknown> {
  if (!projectId) throw new ApiError('没有选中的项目，请返回项目首页后重新进入', 'NO_PROJECT');
  const form = new FormData();
  files.forEach(file => form.append('files', file, file.name));
  form.append('expected_revision', String(revision));
  form.append('projection', 'rectilinear');
  let response: Response;
  try {
    response = await fetch(`${prefix}/projects/${encodeURIComponent(projectId)}/imports`, {
      method: 'POST', body: form, headers: {'Idempotency-Key': requestKey()},
    });
  } catch (error) {
    throw new ApiError(error instanceof TypeError || error instanceof DOMException
      ? '无法发起素材上传，请刷新页面后重试'
      : (error as Error).message, 'UPLOAD_REQUEST_FAILED');
  }
  const result = await response.json().catch(() => null) as {error?: {message?: string; code?: string; action?: string}} | null;
  if (!response.ok) throw new ApiError(result?.error?.message ?? `导入失败 (${response.status})`,
                                      result?.error?.code ?? 'UNKNOWN', result?.error?.action);
  return result;
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
