import { requestClient } from '#/api/request';
import type { KmDoc } from './kb';

export interface FileVersion { id: string; doc_id: string; version: string; created_at: string; project_job: string; current: boolean }
export interface DiffResult { doc: KmDoc; old: string; new: string; rows: { left?: string; right?: string; type: string }[]; stats: { added: number; removed: number; modified: number } }
export interface CleanupScope { target: 'chunks' | 'graph'; doc_id?: string; job_id?: string; library?: string; project?: string; version?: string; chunk_ids?: string[] }
export interface CleanupPreview { title: string; token: string; counts: { files: number; chunks: number; vectors: number; nodes: number; edges: number } }
export const getFileVersions = (id: string) => requestClient.get<FileVersion[]>(`/knowledge/docs/${id}/comparison-versions`);
export const compareFileVersions = (id: string, old: string, current: string) => requestClient.get<DiffResult>(`/knowledge/docs/${id}/comparison`, { params: { old, new: current } });
export const getProjectVersions = (library = '', project = '') => requestClient.get<{ id: string; version: string; library: string; project: string }[]>('/knowledge/project-versions', { params: { library, project } });
export const previewCleanup = (scope: CleanupScope) => requestClient.post<CleanupPreview>('/knowledge/cleanup/preview', scope);
export const executeCleanup = (scope: CleanupScope, token: string) => requestClient.post<CleanupPreview>('/knowledge/cleanup/execute', { ...scope, confirmation_token: token });
export const getFileMapping = (id: string, direction: string, version_id: string) => requestClient.get<{
  file: { key: string; label: string; version: string; kb: string; project: string; content: string };
  relatedDocs: { id: string; name: string; section: string; version: string; version_id: string; project: string }[];
  symbol: string;
}>(`/knowledge/codemap/${id}`, { params: { direction, version_id } });
