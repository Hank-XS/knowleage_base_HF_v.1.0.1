<script lang="ts" setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Empty, InputSearch, Select, Spin, Tag, message } from 'ant-design-vue';
import { getKmChunks, getKmDoc, listKmVersions } from '#/api/kb';
import { requestClient } from '#/api/request';
import { confirmCleanup } from '../cleanup';
import { useFileScope } from '../file-scope';
import FileBrowser from '../FileBrowser.vue';

defineOptions({ name: 'KnowledgeChunk' });
const route = useRoute(); const router = useRouter(); const scope = useFileScope();
const { catalog, library, project, tag, fileId: docId, file: doc, records, page, total, loading: filesLoading, systems, projects } = scope;
const version = ref(''); const versions = ref<{ label: string; value: string }[]>([]); const content = ref(''); const chunks = ref<any[]>([]); const warnings = ref<string[]>([]);
const selectedId = ref(''); const keyword = ref(''); const busy = ref(false); const marker = ref<HTMLElement>(); let sequence = 0;
const filtered = computed(() => chunks.value.filter(c => !keyword.value || `${c.title} ${c.text}`.toLowerCase().includes(keyword.value.toLowerCase())));
const selected = computed(() => chunks.value.find(c => c.id === selectedId.value));
const sourceParts = computed(() => { const chars = Array.from(content.value), current = selected.value; return current ? [chars.slice(0, current.start).join(''), chars.slice(current.start, current.end).join(''), chars.slice(current.end).join('')] : [content.value, '', '']; });
const kinds: Record<string,string> = { function: '段落 / SECTION', variable: '数据定义', constant: '条件定义', file: '文件兜底', section: '章节', table: '表格', code: '代码块', heading: '标题', paragraph: '段落' };
function location(chunk: any) { const m = chunk.meta || {}; return m.start_line ? `L${m.start_line}–L${m.end_line}` : m.page_start ? `第 ${m.page_start}${m.page_end !== m.page_start ? `–${m.page_end}` : ''} 页` : `${chunk.text.length} 字符`; }
async function loadDetail(changed = false, requestedVersion = '') {
  const request = ++sequence;
  if (!docId.value) { content.value = ''; chunks.value = []; doc.value = undefined; busy.value = false; return; }
  busy.value = true;
  try {
    if (changed || !doc.value) { const id = docId.value; const [current, all] = await Promise.all([getKmDoc(id), listKmVersions(id)]); if (request !== sequence) return; doc.value = current; versions.value = all.map(v => ({ label: v.version, value: v.version })); version.value = all.some(v => v.version === requestedVersion) ? requestedVersion : current.version; keyword.value = ''; }
    const data: any = await getKmChunks(docId.value, { version: version.value }); if (request !== sequence) return;
    content.value = data.content; chunks.value = data.chunks; warnings.value = data.warnings || []; selectedId.value = chunks.value[0]?.id || '';
  } catch (e: any) { if (request === sequence) message.error(e.message || '读取切片失败'); } finally { if (request === sequence) busy.value = false; }
}
async function chooseFile(id: string) { docId.value = id; await loadDetail(true); }
async function chooseFirst() { await chooseFile(records.value[0]?.id || ''); }
async function filterChanged(system = false) { sequence++; busy.value = false; content.value = ''; chunks.value = []; versions.value = []; warnings.value = []; await scope.reset(system); await chooseFirst(); }
async function browse(pageNumber = 1, search?: string) { page.value = pageNumber; if (search !== undefined) scope.search.value = search; await scope.loadFiles(); await chooseFirst(); }
async function selectChunk(id: string) { selectedId.value = id; await nextTick(); const mark = marker.value, scroller = mark?.closest('pre'); if (mark && scroller) scroller.scrollTo({ top: scroller.scrollTop + mark.getBoundingClientRect().top - scroller.getBoundingClientRect().top - scroller.clientHeight / 2, behavior: 'smooth' }); }
async function download() { if (!doc.value) return; try { const blob = await requestClient.get<Blob>(`/knowledge/docs/${docId.value}/original`, { params: { version: version.value }, responseType: 'blob', responseReturn: 'body' }); const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; const name = doc.value.name.split('/').pop() || doc.value.name; a.download = name.toLowerCase().endsWith('.' + doc.value.type.toLowerCase()) ? name : `${name}.${doc.value.type}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); } catch (e: any) { message.error(e.message || '下载失败'); } }
async function cleanup(chunkId = '') { await confirmCleanup({ target: 'chunks', doc_id: docId.value, version: version.value, ...(chunkId ? { chunk_ids: [chunkId] } : {}) }, () => loadDetail()); }
async function refresh() { await scope.initialize(route.query); if (docId.value) await loadDetail(true, String(route.query.version || '')); else await chooseFirst(); }
onMounted(refresh); watch(() => route.fullPath, () => { if (route.path === '/knowledge/chunk') void refresh(); else { sequence++; busy.value = false; } }); onBeforeUnmount(() => { sequence++; });
</script>
<template>
  <Page>
    <div class="heading"><div><small>内容管理 / 原文与切片</small><h1>切片查看</h1><p>筛选资料后，从左侧直接选择文件，在本页阅读原文和结构切片。</p></div><Button @click="router.push('/knowledge/docs')">返回知识库</Button></div>
    <Card class="filter-card"><div class="filters"><label>所属系统<Select :value="library || undefined" @update:value="library = String($event || '')" :options="systems" allow-clear show-search option-filter-prop="label" placeholder="全部系统" @change="filterChanged(true)" /></label><label>工程<Select :value="project || undefined" @update:value="project = String($event || '')" :options="projects" allow-clear show-search option-filter-prop="label" placeholder="全部工程" @change="filterChanged()" /></label><label>主题标签<Select :value="tag || undefined" @update:value="tag = String($event || '')" :options="catalog.tags.map(t => ({ label:t.value, value:t.value }))" allow-clear placeholder="全部主题" @change="filterChanged()" /></label></div></Card>
    <div class="file-layout"><FileBrowser :search="scope.search.value" :items="records" :selected="docId" :total="total" :page="page" :loading="filesLoading" @select="chooseFile" @search="browse(1, $event)" @page="browse($event)" />
      <Spin :spinning="busy"><div v-if="doc"><div class="doc-summary"><strong>{{ doc.name }}</strong><Tag>{{ doc.type.toUpperCase() }}</Tag><Select v-model:value="version" :options="versions" style="width:140px" @change="loadDetail()" /><Button size="small" @click="download">下载原文件</Button><Button v-if="doc.asset_type === 'code'" size="small" @click="router.push({ path: '/kb/graph', query: { doc: docId } })">代码关系图</Button><Button size="small" @click="router.push({ path: '/knowledge/diff', query: { doc: docId } })">版本对比</Button><Button danger size="small" :disabled="!chunks.length" @click="cleanup()">清理切片</Button></div><Alert v-for="w in warnings" :key="w" type="warning" show-icon :message="w" class="warning" />
      <div class="workspace"><Card title="原文内容" class="source"><template #extra><small>{{ Array.from(content).length.toLocaleString() }} 字符</small></template><pre v-if="selected">{{ sourceParts[0] }}<mark ref="marker">{{ sourceParts[1] }}</mark>{{ sourceParts[2] }}</pre><pre v-else>{{ content }}</pre></Card><Card :title="`结构切片 · ${chunks.length}`" class="slices"><InputSearch v-model:value="keyword" placeholder="搜索章节、结构名称或内容" allow-clear /><div class="slice-list"><article v-for="(c,i) in filtered" :key="c.id" class="slice" :class="{active:selectedId === c.id}"><button class="slice-select" @click="selectChunk(c.id)"><div><Tag>{{ kinds[c.meta?.kind] || '结构切片' }}</Tag><small>{{ location(c) }}</small></div><strong>{{ c.title }}</strong><p>{{ c.text.slice(0,160) }}{{ c.text.length > 160 ? '…' : '' }}</p></button><div class="slice-footer"><small>#{{ i + 1 }} · {{ c.text.length }} 字符</small><Button danger size="small" type="link" @click="cleanup(c.id)">删除切片</Button></div></article><Empty v-if="!filtered.length" :description="chunks.length ? '没有匹配的切片' : '此版本没有切片，重新上传解析后可恢复'" /></div></Card></div></div><Card v-else><Empty description="当前范围没有文件，调整筛选条件后可继续浏览" /></Card></Spin>
    </div>
  </Page>
</template>
<style scoped>
.heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.heading h1{font-size:26px;margin:6px 0}.heading p,small{color:hsl(var(--muted-foreground))}.filters{display:flex;gap:16px;flex-wrap:wrap}.filters>label{display:flex;flex:1;flex-direction:column;gap:8px;min-width:180px;font-size:13px}.file-layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:18px;margin-top:20px;align-items:start}.doc-summary{display:flex;gap:8px;align-items:center;margin-bottom:16px;flex-wrap:wrap}.doc-summary>strong{width:100%;overflow-wrap:anywhere}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}.source pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.8;max-height:max(300px,calc(100vh - 500px));overflow:auto;padding:14px;background:hsl(var(--muted));border-radius:8px}.source mark{background:#fff0af;color:#422006}.slice-list{max-height:max(280px,calc(100vh - 560px));overflow:auto;margin-top:16px}.slice{padding:14px;border:1px solid hsl(var(--border));border-radius:8px;margin-bottom:10px}.slice.active{border-color:hsl(var(--primary));background:hsl(var(--primary)/.08)}.slice-select{display:block;width:100%;text-align:left;color:inherit;cursor:pointer}.slice-select>div,.slice-footer{display:flex;justify-content:space-between;align-items:center;gap:6px}.slice strong{display:block;overflow-wrap:anywhere;margin-top:10px}.slice p{color:hsl(var(--muted-foreground));white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;margin:8px 0}.warning{margin-bottom:14px}@media(max-width:1300px){.workspace{grid-template-columns:1fr}.source pre,.slice-list{max-height:400px}}@media(max-width:850px){.file-layout{grid-template-columns:1fr}}
</style>
