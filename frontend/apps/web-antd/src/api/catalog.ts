import { requestClient } from '#/api/request';
export interface CatalogOptions {
  libraries: { key: string; title: string; children?: { key: string; title: string }[] }[];
  projects: { library: string; name: string }[];
  purposes: { value: string; label: string }[];
  tags: { value: string; count: number }[];
}
export interface Asset {
  id: string; name: string; asset_type: string; library: string; project: string; purpose: string;
  version: string; status: string; tags: string[]; is_current: boolean; uploadedAt: string;
  file_count: number; chunk_count: number; program_count?: number; copybook_count?: number;
  error?: string; warnings?: number;
  attempt_status?: string; attempt_error?: string; attempt_version?: string;
}
export const getCatalog = (params: Record<string, any> = {}) => requestClient.get<CatalogOptions>('/knowledge/catalog', { params });
export const getAssets = (params: Record<string, any>) => requestClient.get<{
  items: Asset[]; total: number; stats: { projects: number; documents: number; files: number; chunks: number };
}>('/knowledge/assets', { params });
export const createSystem = (title: string) => requestClient.post<{ key: string }>('/knowledge/libraries', {
  title,
});
