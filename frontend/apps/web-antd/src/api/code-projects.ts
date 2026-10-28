import { requestClient } from '#/api/request';

export interface ProjectFile {
  path: string;
  indexed: boolean;
  errors: string;
  structural_chunks: boolean;
  chunks: number;
}
export interface ProjectJob {
  job_id: string;
  project: string;
  version: string;
  library: string;
  filename: string;
  status: string;
  error: string;
  active: boolean;
  superseded_by?: string;
  created_at: string;
  steps: { step: string; status: string; detail: string }[];
  summary?: Record<string, number>;
  files: ProjectFile[] | string[];
  skipped: { path: string; reason: string }[];
  unresolved?: { name: string; kind: string; path: string; line: number }[];
  embedding?: string;
  engine_version?: string;
}
export interface ProjectChunk {
  id: string;
  node_id: string;
  title: string;
  path: string;
  start_line: number;
  end_line: number;
  text: string;
}
export interface ProjectNode {
  id: string;
  label: string;
  props: { name: string; path: string; kind: string; start_line: number; end_line: number };
}
export interface ProjectGraph {
  nodes: ProjectNode[];
  edges: { src: string; dst: string; rel: string; props: { line: number } }[];
  truncated: boolean;
  total: number;
}
export const uploadCodeProject = (data: FormData) => requestClient.post<ProjectJob>('/code-projects', data);
export const listCodeProjects = () => requestClient.get<ProjectJob[]>('/code-projects');
export const getCodeProject = (id: string) => requestClient.get<ProjectJob>(`/code-projects/${id}`);
export const retryCodeProject = (id: string) => requestClient.post<ProjectJob>(`/code-projects/${id}/retry`);
export const getProjectChunks = (id: string, path = '', page = 1) =>
  requestClient.get<{ items: ProjectChunk[]; total: number }>(`/code-projects/${id}/chunks`, { params: { path, page, page_size: 20 } });
export const getProjectGraph = (id: string, path = '') =>
  requestClient.get<ProjectGraph>(`/code-projects/${id}/graph`, { params: { path } });
export const getProjectSource = (id: string, path: string) =>
  requestClient.get<{ content: string; path: string; lines: number }>(`/code-projects/${id}/source`, { params: { path } });
