/**
 * 知识库后端 API 封装（对应后端设计第 7 章 REST 接口）
 */
import { requestClient } from '#/api/request';

export interface KbSource {
  label: string;
  loc: string;
  no: number;
  obj: string;
  /** 文档相对路径或图谱节点 id，用于预览 */
  path?: string;
  ref: string;
  score?: number;
  snippet: string;
  type: string;
}

export interface KbSourcePreview {
  available: boolean;
  content: string;
  from_cache: boolean;
  loc: string;
  path: string;
  snippet?: string;
  title: string;
  type: string;
}

export interface KbAnswer {
  caveats?: string[];
  confidence?: number;
  how: string;
  uncovered?: boolean;
  what: string;
  why: string;
}

export interface KbAnswerPayload {
  answer: KbAnswer;
  answer_id: string;
  elapsed_ms: number;
  entities: string[];
  hit_type: 'exact' | 'miss' | 'similar';
  intent: string;
  reasoning_trace: { result: string; step: number; tool: string }[];
  review_status: string;
  similarity: number;
  sources: KbSource[];
}

export interface TaggingTask {
  created_at: string;
  id: string;
  items: TagItem[];
  operator: string;
  status: string;
  title: string;
  task_type: string;
}

export interface TagItem {
  item_id: string;
  node_id: string;
  reason?: string;
  source: string;
  status: string;
  tag: { category: string; value: string };
}

export interface IngestJob {
  created_at: string;
  error: string;
  job_id: string;
  object_keys: string[];
  source_type: string;
  status: string;
  steps: { detail: string; status: string; step: string }[];
}

export interface GraphNode {
  id: string;
  label: string;
  name: string;
  props: Record<string, any>;
}

export interface GraphEdge {
  dst: string;
  rel: string;
  src: string;
}

/** 创建问答会话 */
export function createSession() {
  return requestClient.post<{ scene_code: string; session_id: string }>(
    '/qa/sessions',
    {},
  );
}

/** 提问（单一 Flow） */
export function ask(sessionId: string, question: string) {
  return requestClient.post<KbAnswerPayload>('/qa/ask', {
    question,
    session_id: sessionId,
  });
}

/** 提问（Agent：自动调度 search_doc / search_code / search_graph 等工具） */
export function askAgent(sessionId: string, question: string) {
  return requestClient.post<KbAnswerPayload & { orchestrator?: string }>(
    '/qa/ask_agent',
    {
      mode: 'agent',
      question,
      session_id: sessionId,
    },
  );
}

/** 答案人工复核 */
export function reviewAnswer(
  answerId: string,
  verdict: 'approved' | 'rejected',
) {
  return requestClient.post<any>(`/qa/answers/${answerId}/review`, {
    verdict,
  });
}

/** 依据来源文档预览 */
export function previewSource(params: {
  answer_id?: string;
  label?: string;
  loc?: string;
  no?: number;
  obj?: string;
  path?: string;
  ref?: string;
  snippet?: string;
  type?: string;
}) {
  return requestClient.get<KbSourcePreview>('/qa/sources/preview', { params });
}

/** 打标任务列表 */
export function listTaggingTasks(status?: string) {
  return requestClient.get<{
    items: TaggingTask[];
    limit: number;
    pending_total: number;
    total: number;
  }>('/governance/tagging-tasks', {
    params: status ? { status } : {},
  });
}

/** 提交打标校对 */
export function submitTagReview(
  taskId: string,
  items: { action: string; item_id: string; reason?: string }[],
) {
  return requestClient.put<any>(`/governance/tagging-tasks/${taskId}`, {
    items,
  });
}

/** 批量通过/驳回（支持 all_pending 清空全部待校对） */
export function batchTagReview(body: {
  action: 'accept' | 'reject';
  all_pending?: boolean;
  reason?: string;
  task_ids?: string[];
}) {
  return requestClient.post<{
    applied: number;
    errors: { error: string; task_id: string }[];
    processed: number;
    rejected: number;
    remaining_pending: number;
  }>('/governance/tagging-tasks/batch-review', body);
}

/** 素材接入（上传→六步流水线：含 clean） */
export function createIngestJob(file: File, sourceType: string) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('source_type', sourceType);
  return requestClient.post<IngestJob>('/ingest/jobs', fd);
}

export function listIngestJobs() {
  return requestClient.get<IngestJob[]>('/ingest/jobs');
}

/** 数据集全量清洗（hf_data → 08_cleaned） */
export function runDatasetClean(doImport = false, includeTierC = false) {
  return requestClient.post<{
    clean: {
      conflicts: number;
      kg_triples: number;
      quarantine: number;
      rule_hits: Record<string, number>;
      stats: Record<string, number>;
      vector_chunks: number;
    };
    govern_tasks: { conflict_task?: string; quarantine_task?: string };
    imported: null | { chunks: number; edges: number; nodes: number };
    job_id: string;
  }>('/ingest/clean/run', {
    do_import: doImport,
    include_tier_c: includeTierC,
  });
}

export function importCleaned(includeTierC = false, minTrust = 0) {
  return requestClient.post<{ chunks: number; edges: number; nodes: number }>(
    '/ingest/clean/import',
    { include_tier_c: includeTierC, min_trust: minTrust },
  );
}

export function getCleanManifest() {
  return requestClient.get<{
    conflicts?: number;
    dataset_root?: string;
    exists: boolean;
    generated_at?: string;
    kg_triples?: number;
    notes?: string[];
    out_dir?: string;
    quarantine?: number;
    root?: string;
    rule_hits?: Record<string, number>;
    stats?: Record<string, number>;
    vector_chunks?: number;
  }>('/ingest/clean/manifest');
}

export function listCleanQuarantine(limit = 50) {
  return requestClient.get<{ items: any[]; total: number }>(
    '/ingest/clean/quarantine',
    { params: { limit } },
  );
}

export function listCleanConflicts(limit = 50) {
  return requestClient.get<{ items: any[]; total: number }>(
    '/ingest/clean/conflicts',
    { params: { limit } },
  );
}

/** 影响分析 */
export function analyzeImpact(target: string, changeSummary = '') {
  return requestClient.post<any>('/impact/analyze', {
    change_summary: String(changeSummary ?? ''),
    target: String(target ?? ''),
  });
}

/** 代码骨架生成 */
export function generateSkeleton(interfaceId: string, target: string) {
  const lang =
    target === 'python_script' ? 'python_script' : 'spring_controller';
  return requestClient.post<any>('/codegen/skeleton', {
    interface_id: String(interfaceId ?? ''),
    target: lang,
  });
}

/** hf_data 代码资产树 */
export function getCodeTree() {
  return requestClient.get<any>('/kb/code-tree');
}

export function previewCodeTree(path: string, symbol = '') {
  return requestClient.get<any>('/kb/code-tree/preview', {
    params: { path, symbol },
  });
}

/** 基于知识库为粘贴代码生成注释（结果落库） */
export function annotateCode(body: {
  code: string;
  hint?: string;
  language?: string;
  path?: string;
  symbol?: string;
}) {
  return requestClient.post<any>('/codegen/annotate', {
    code: String(body.code ?? ''),
    language: String(body.language ?? 'cobol'),
    hint: String(body.hint ?? ''),
    path: String(body.path ?? ''),
    symbol: String(body.symbol ?? ''),
  });
}

/** 基于已生成注释 + 式样书提示词增强（结果落库） */
export function generateSpec(body: {
  annotated_code?: string;
  code?: string;
  hint?: string;
  language?: string;
  path?: string;
  prompt_type?: string;
  symbol?: string;
}) {
  return requestClient.post<any>('/codegen/spec', {
    code: String(body.code ?? ''),
    annotated_code: String(body.annotated_code ?? ''),
    prompt_type: String(body.prompt_type ?? ''),
    path: String(body.path ?? ''),
    symbol: String(body.symbol ?? ''),
    language: String(body.language ?? 'cobol'),
    hint: String(body.hint ?? ''),
  });
}

/** 读取本地库中该路径的注释/式样书结果 */
export function getCodeWork(path: string, symbol = '') {
  return requestClient.get<any>('/codegen/work', {
    params: { path, symbol },
  });
}

/** 式样书提示词配置 */
export function listPrompts() {
  return requestClient.get<any[]>('/admin/prompts');
}

export function getPrompt(type: string) {
  return requestClient.get<any>(`/admin/prompts/${encodeURIComponent(type)}`);
}

export function updatePrompt(
  type: string,
  body: { enabled?: boolean; system_prompt?: string; title?: string },
) {
  return requestClient.put<any>(
    `/admin/prompts/${encodeURIComponent(type)}`,
    body,
  );
}

export function resetPrompt(type: string) {
  return requestClient.post<any>(
    `/admin/prompts/${encodeURIComponent(type)}/reset`,
  );
}

/** 系统状态 */
export function getLlmStatus() {
  return requestClient.get<any>('/admin/llm-status');
}

export function getKbStats() {
  return requestClient.get<any>('/admin/kb-stats');
}

export function listTools() {
  return requestClient.get<any[]>('/admin/tools');
}

export function listVersions() {
  return requestClient.get<any[]>('/kb/versions');
}

/** 图谱检索（三层查全/影响面） */
export function graphSearch(mode: string, params: Record<string, any>) {
  return requestClient.post<any>('/search/graph', { mode, params });
}

/** 图谱全量结构（拓扑可视化） */
export function graphStruct() {
  return requestClient.get<{
    edges: GraphEdge[];
    nodes: GraphNode[];
    stats: { by_label: Record<string, number>; edges: number; nodes: number };
  }>('/graph/struct');
}

/** 标签词表 */
export function listVocab(status?: string) {
  return requestClient.get<
    Array<{ category: string; created_by: string; id: number; status: string; value: string }>
  >('/governance/vocab', { params: status ? { status } : {} });
}

export function addVocab(category: string, value: string) {
  return requestClient.post<any>('/governance/vocab', {
    category,
    value,
  });
}

export function reviewVocab(id: number, action: 'approve' | 'reject') {
  return requestClient.put<any>(`/governance/vocab/${id}`, { action });
}

/** 触发 AI 交叉打标（代码×文档） */
export function triggerCrossTag(limit = 8) {
  return requestClient.post<any>('/governance/cross-tag', { limit });
}

/* ========== 知识库管理 ========== */

export interface KmLibrary {
  children?: KmLibrary[];
  count: number;
  key: string;
  title: string;
}

export interface KmDoc {
  author?: string;
  content?: string;
  id: string;
  kbKey: string;
  name: string;
  official: boolean;
  path: string;
  security: string;
  size: string;
  sourcePath?: string;
  status: string;
  tags?: string[];
  type: string;
  uploadedAt: string;
  vectorized: boolean;
  version: string;
}

export function listKmLibraries() {
  return requestClient.get<KmLibrary[]>('/knowledge/libraries');
}

export function syncKmDataset(force = false) {
  return requestClient.post<any>('/knowledge/sync', {}, {
    params: { force },
  });
}

export function listKmDocs(params: Record<string, any>) {
  return requestClient.get<{
    items: KmDoc[];
    page: number;
    page_size: number;
    total: number;
  }>('/knowledge/docs', { params });
}

export function getKmDoc(id: string) {
  return requestClient.get<KmDoc>(`/knowledge/docs/${id}`);
}

export function deleteKmDoc(id: string) {
  return requestClient.delete<{ deleted: boolean; id: string }>(
    `/knowledge/docs/${id}`,
  );
}

export function batchKmDocStatus(body: {
  action: 'audit' | 'submit';
  doc_ids: string[];
  status: string;
}) {
  return requestClient.post<{ status: string; updated: number }>(
    '/knowledge/docs/batch-status',
    body,
  );
}

export function uploadKmDoc(form: FormData) {
  return requestClient.post<KmDoc>('/knowledge/upload', form);
}

export function getKmChunks(id: string, params?: { keyword?: string; version?: string }) {
  return requestClient.get<{
    chunks: Array<{
      chunk_index: number;
      end: number;
      id: string;
      start: number;
      text: string;
      title: string;
    }>;
    content: string;
    doc: KmDoc;
    version: string;
  }>(`/knowledge/docs/${id}/chunks`, { params });
}

export function listKmVersions(id: string) {
  return requestClient.get<
    Array<{ chars: number; created_at: string; created_by: string; version: string }>
  >(`/knowledge/docs/${id}/versions`);
}

export function getKmDiff(id: string, oldV: string, newV: string) {
  return requestClient.get<{
    doc: KmDoc;
    new: string;
    new_content: string;
    old: string;
    old_content: string;
    rows: Array<{ left?: string; right?: string; type: string }>;
    stats: { added: number; modified: number; removed: number };
  }>(`/knowledge/docs/${id}/diff`, { params: { new: newV, old: oldV } });
}

export function bumpKmVersion(id: string, newVersion: string, note = '') {
  return requestClient.post<KmDoc>(`/knowledge/docs/${id}/versions`, {
    new_version: newVersion,
    note,
  });
}

export function listKmCodeFiles(kb = '') {
  return requestClient.get<
    Array<{ kb: string; key: string; label: string; path: string; version: string }>
  >('/knowledge/codemap', { params: kb ? { kb } : {} });
}

export function getKmCodeMap(docId: string) {
  return requestClient.get<{
    file: {
      content: string;
      kb: string;
      key: string;
      label: string;
      version: string;
    };
    relatedDocs: Array<{ id: string; name: string; section: string }>;
    symbol: string;
  }>(`/knowledge/codemap/${docId}`);
}
