<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Checkbox, Drawer, Dropdown, Empty, InputSearch, Menu, MenuItem, Select, Space, Table, Tag, message } from 'ant-design-vue';
import { getAssets, getCatalog, type Asset, type CatalogOptions } from '#/api/catalog';
import { listKmDocs, type KmDoc } from '#/api/kb';
import { confirmCleanup } from '../cleanup';
defineOptions({ name: 'KnowledgeDocs' });
const route = useRoute(); const router = useRouter();
const catalog = ref<CatalogOptions>({ libraries: [], projects: [], purposes: [], tags: [] });
const library = ref(String(route.query.kb || '')); const project = ref(String(route.query.project || ''));
const type = ref(''); const purpose = ref(''); const tag = ref(''); const keyword = ref(''); const history = ref(false);
const loading = ref(false); const rows = ref<Asset[]>([]); const page = ref(1); const total = ref(0);
const stats = ref({ projects: 0, documents: 0, files: 0, chunks: 0 });
const opened = ref<Asset>(); const fileRows = ref<KmDoc[]>([]); const filePage = ref(1); const fileTotal = ref(0); const fileKeyword = ref(''); const fileLoading = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined; let request = 0;
const systems = computed(() => catalog.value.libraries.flatMap(l => [{ label: l.title, value: l.key }, ...(l.children || []).map(c => ({ label: `${l.title} / ${c.title}`, value: c.key }))]));
const projects = computed(() => [...new Set(catalog.value.projects.filter(p => !library.value || p.library === library.value).map(p => p.name))].map(name => ({ label: name, value: name })));
const columns = [{ title: '资料 / 工程', key: 'name' }, { title: '归属与用途', key: 'classification' }, { title: '版本', key: 'version', width: 120 }, { title: '主题标签', key: 'tags' }, { title: '处理状态', key: 'status', width: 130 }, { title: '上传时间', dataIndex: 'uploadedAt', key: 'time', width: 170 }, { title: '操作', key: 'actions', width: 230 }];
const fileColumns = [{ title: '文件路径', dataIndex: 'name', key: 'name' }, { title: '文件角色', key: 'role', width: 140 }, { title: '操作', key: 'actions', width: 250 }];
const purposeName = (value: string) => catalog.value.purposes.find(p => p.value === value)?.label || (value === 'source' ? '工程源码' : '参考资料');
const systemName = (key: string) => systems.value.find(l => l.value === key)?.label || key;
async function load() {
  clearTimeout(timer); const id = ++request; loading.value = true;
  try { const data = await getAssets({ kb: library.value, project: project.value, asset_type: type.value, purpose: purpose.value, tag: tag.value, keyword: keyword.value, history: history.value, page: page.value });
    if (id !== request) return; rows.value = data.items; total.value = data.total; stats.value = data.stats;
    if (rows.value.some(r => ['queued', 'running'].includes(r.attempt_status || r.status))) timer = setTimeout(load, 3000);
  } catch (e: any) { message.error(e.message || '读取资料失败'); } finally { if (id === request) loading.value = false; }
}
async function loadFiles() {
  if (!opened.value) return; fileLoading.value = true;
  try { const data = await listKmDocs({ project_job: opened.value.id, history: true, keyword: fileKeyword.value, page: filePage.value, page_size: 15 }); fileRows.value = data.items; fileTotal.value = data.total; }
  finally { fileLoading.value = false; }
}
async function openFiles(asset: Asset) { opened.value = asset; filePage.value = 1; fileKeyword.value = ''; await loadFiles(); }
function openChunk(id: string) { router.push({ path: '/knowledge/chunk', query: { doc: id } }); }
function graph(asset: Asset) { router.push({ path: '/kb/graph', query: asset.asset_type === 'project' ? { library: asset.library, project: asset.project, version: asset.version } : { doc: asset.id } }); }
async function cleanup(asset: Asset, target: 'chunks' | 'graph') { await confirmCleanup({ target, ...(asset.asset_type === 'project' ? { job_id: asset.id } : { doc_id: asset.id, version: asset.version }) }, async () => { await load(); catalog.value = await getCatalog(); }); }
watch(library, () => { project.value = ''; }, { flush: 'sync' });
watch([library, project, type, purpose, tag, history], () => { page.value = 1; void load(); });
async function refresh() { library.value = String(route.query.kb || library.value || ''); project.value = String(route.query.project || project.value || ''); catalog.value = await getCatalog(); await load(); }
onMounted(refresh);
watch(() => route.fullPath, () => { if (route.path === '/knowledge/docs') void refresh(); else { clearTimeout(timer); request++; loading.value = false; } });
onBeforeUnmount(() => { clearTimeout(timer); request++; });
</script>
<template>
  <Page>
    <div class="header"><div><small>内容管理 / 全部资产</small><h1>知识库列表</h1><p>按系统归档，按工程聚合，让资料和代码保持清晰的关系。</p></div><Button type="primary" size="large" @click="router.push({ path: '/knowledge/upload', query: { kb: library } })">上传资料</Button></div>
    <div class="metrics"><Card v-for="m in [{ label: history ? '工程版本' : '代码工程', value: stats.projects }, { label: '文档资料', value: stats.documents }, { label: history ? '文件（含历史）' : '文件', value: stats.files }, { label: history ? '切片（含历史）' : '切片', value: stats.chunks }]" :key="m.label"><span>{{ m.label }}</span><strong>{{ m.value.toLocaleString() }}</strong></Card></div>
    <Card class="catalog-card">
      <div class="filters">
        <Select :value="library || undefined" @update:value="library = String($event || '')" allow-clear :options="systems" placeholder="全部系统" show-search option-filter-prop="label" @clear="library = ''" />
        <Select :value="project || undefined" @update:value="project = String($event || '')" allow-clear :options="projects" placeholder="全部工程" show-search option-filter-prop="label" @clear="project = ''" />
        <Select v-model:value="type" :options="[{ label: '全部资料', value: '' }, { label: '代码工程', value: 'project' }, { label: '文档资料', value: 'document' }]" />
        <Select :value="purpose || undefined" @update:value="purpose = String($event || '')" allow-clear :options="catalog.purposes" placeholder="全部用途" @clear="purpose = ''" />
        <Select :value="tag || undefined" @update:value="tag = String($event || '')" allow-clear :options="catalog.tags.map(t => ({ label: t.value, value: t.value }))" placeholder="主题标签" show-search @clear="tag = ''" />
        <InputSearch v-model:value="keyword" placeholder="搜索名称、工程或标签" @search="page = 1; load()" />
      </div>
      <div class="list-caption"><span>共 {{ total }} 项资料 · 工程按整包聚合，文件在工程内查看</span><Checkbox v-model:checked="history">显示历史工程版本</Checkbox><Button size="small" @click="load">刷新</Button></div>
      <Table :columns="columns" :data-source="rows" row-key="id" :loading="loading" :scroll="{ x: 1000 }" :pagination="{ current: page, total, pageSize: 20, showSizeChanger: false }" @change="p => { page = p.current || 1; load(); }">
        <template #emptyText><Empty description="还没有资料，上传文档或代码工程开始建立知识库"><Button type="primary" @click="router.push('/knowledge/upload')">上传第一份资料</Button></Empty></template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'"><div class="asset-name"><Tag :color="record.asset_type === 'project' ? 'blue' : 'cyan'">{{ record.asset_type === 'project' ? '工程' : '文档' }}</Tag><strong>{{ record.name }}</strong></div><small v-if="record.asset_type === 'project'">{{ record.file_count }} 个文件 · {{ record.program_count }} 个程序 · {{ record.copybook_count }} 个 Copybook</small></template>
          <template v-else-if="column.key === 'classification'"><div>{{ systemName(record.library) }}</div><small>{{ record.project || '系统通用' }} · {{ purposeName(record.purpose) }}</small></template>
          <template v-else-if="column.key === 'version'"><div>{{ record.version }}</div><small>{{ record.is_current ? '当前版本' : ['queued', 'running', 'failed'].includes(record.status) ? '待入库版本' : '历史版本' }}</small></template>
          <template v-else-if="column.key === 'tags'"><Tag v-for="t in record.tags" :key="t" @click="tag = t" style="cursor:pointer">{{ t }}</Tag><small v-if="!record.tags.length">未添加主题标签</small></template>
          <template v-else-if="column.key === 'status'"><Tag :color="['done','published'].includes(record.status) ? 'green' : record.status === 'failed' ? 'red' : 'blue'">{{ ({ done: '已入库', published: '已入库', queued: '等待解析', running: '解析中', failed: '处理失败', draft: '已保存' } as any)[record.status] || record.status }}</Tag><div><small>{{ record.chunk_count }} 个切片</small></div><small v-if="record.error" class="error">{{ record.error }}</small><small v-if="record.warnings">{{ record.warnings }} 个文件需关注</small><div v-if="record.attempt_status && record.attempt_status !== 'done'" class="attempt"><Tag :color="record.attempt_status === 'failed' ? 'orange' : 'blue'">{{ record.attempt_version }} {{ record.attempt_status === 'failed' ? '更新失败' : '更新中' }}</Tag><small v-if="record.attempt_status === 'failed'" class="error">{{ record.attempt_error }}</small></div></template>
          <template v-else-if="column.key === 'time'">{{ record.uploadedAt.slice(0,19).replace('T',' ') }}</template>
          <template v-else-if="column.key === 'actions'"><Space><Button type="link" @click="record.asset_type === 'project' ? openFiles(record as Asset) : openChunk(record.id)">{{ record.asset_type === 'project' ? '查看文件' : '查看切片' }}</Button><Button type="link" @click="graph(record as Asset)">图谱</Button><Dropdown><Button type="link">清理</Button><template #overlay><Menu><MenuItem @click="cleanup(record as Asset, 'chunks')">清理此版本切片</MenuItem><MenuItem @click="cleanup(record as Asset, 'graph')">清理此版本图谱</MenuItem></Menu></template></Dropdown></Space></template>
        </template>
      </Table>
    </Card>
    <Drawer :open="!!opened" :title="opened ? `${opened.name} · ${opened.version}` : ''" width="min(850px, 95vw)" @close="opened = undefined">
      <template #extra><Button v-if="opened" type="link" @click="router.push(`/kb/code-projects/${opened.id}`)">解析报告</Button></template>
      <Alert v-if="opened?.error" type="error" :message="opened.error" show-icon />
      <p class="drawer-description">保留 ZIP 中的文件路径，可从任一文件进入切片与源码。</p>
      <InputSearch v-model:value="fileKeyword" placeholder="搜索文件名或路径" @search="filePage = 1; loadFiles()" />
      <Table :columns="fileColumns" :data-source="fileRows" row-key="id" :loading="fileLoading" :pagination="{ current: filePage, total: fileTotal, pageSize: 15, showSizeChanger: false }" @change="p => { filePage = p.current || 1; loadFiles(); }">
        <template #bodyCell="{ column, record }"><template v-if="column.key === 'role'"><Tag>{{ record.type === 'cpy' ? record.name.includes('cpy-bms/') ? 'BMS Copybook' : 'Copybook' : 'COBOL 程序' }}</Tag></template><Space v-else-if="column.key === 'actions'"><Button type="link" @click="openChunk(record.id)">查看切片</Button><Button type="link" @click="router.push({ path: '/kb/graph', query: { doc: record.id } }); opened = undefined">代码关系图</Button><Button type="link" @click="router.push({ path: '/knowledge/diff', query: { doc: record.id } }); opened = undefined">版本对比</Button></Space></template>
      </Table>
    </Drawer>
  </Page>
</template>
<style scoped>
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.header h1{font-size:26px;margin:6px 0}.header p,small{color:#64748b}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px}.metrics span{color:#64748b}.metrics strong{display:block;font-size:28px;margin-top:8px}.filters{display:flex;flex-wrap:wrap;gap:12px}.filters>.ant-select{min-width:150px;flex:1}.filters>.ant-input-group-wrapper{width:260px}.list-caption{display:flex;gap:16px;align-items:center;margin:24px 0 14px;color:#64748b}.list-caption>span{flex:1}.asset-name{margin-bottom:6px}.error{display:block;color:#dc2626}.attempt{margin-top:8px}.drawer-description{color:#64748b}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,1fr)}.header p{max-width:260px}.list-caption{flex-wrap:wrap}}
</style>
