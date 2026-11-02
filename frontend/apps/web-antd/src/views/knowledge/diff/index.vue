<script lang="ts" setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Empty, RadioButton, RadioGroup, Select, Spin, Tag, message } from 'ant-design-vue';
import { getKmDoc } from '#/api/kb';
import { compareFileVersions, getFileVersions, type FileVersion, type DiffResult } from '#/api/knowledge-browse';
import { useFileScope } from '../file-scope';
import FileBrowser from '../FileBrowser.vue';

defineOptions({ name: 'KnowledgeDiff' });
const route = useRoute(); const router = useRouter();
const scope = useFileScope(); const { catalog, library, project, tag, fileId, file, systems, projects, records, loading: filesLoading, page, total } = scope;
const versions = ref<FileVersion[]>([]); const oldId = ref(''); const newId = ref('');
const mode = ref('side'); const loading = ref(false); const result = ref<DiffResult>(); let sequence = 0;
async function compare() {
  const id = ++sequence;
  if (!fileId.value || !oldId.value || !newId.value || oldId.value === newId.value) { result.value = undefined; loading.value = false; return; }
  loading.value = true;
  try { const data = await compareFileVersions(fileId.value, oldId.value, newId.value); if (id === sequence) result.value = data; }
  catch (e: any) { message.error(e.response?.data?.message || e.message || '对比失败'); }
  finally { if (id === sequence) loading.value = false; }
}
async function selectFile() {
  sequence++; loading.value = false; result.value = undefined; versions.value = []; oldId.value = ''; newId.value = ''; const requested = fileId.value;
  if (!requested) return;
  try {
    const [doc, rows] = await Promise.all([getKmDoc(requested), getFileVersions(requested)]);
    if (requested !== fileId.value) return;
    file.value = doc; versions.value = rows; oldId.value = rows[0]?.id || ''; newId.value = rows.at(-1)?.id || ''; await compare();
  } catch (e: any) { message.error(e.message || '读取文件版本失败'); }
}
async function filterChanged(system = false) { sequence++; loading.value = false; result.value = undefined; versions.value = []; oldId.value = ''; newId.value = ''; await scope.reset(system); await chooseFile(records.value[0]?.id || ''); }
async function chooseFile(id: string) { fileId.value = id; await selectFile(); }
async function browse(pageNumber = 1, search?: string) { page.value = pageNumber; if (search !== undefined) scope.search.value = search; await scope.loadFiles(); await chooseFile(records.value[0]?.id || ''); }
async function refresh() { await scope.initialize(route.query); await chooseFile(fileId.value || records.value[0]?.id || ''); }
onMounted(refresh); watch(() => route.fullPath, () => { if (route.path === '/knowledge/diff') void refresh(); });
onBeforeUnmount(() => { sequence++; });
</script>
<template>
  <Page>
    <div class="heading"><div><small>内容管理 / 版本追溯</small><h1>版本对比</h1><p>按系统、工程和文件选择实际上传版本，检查代码或文档的内容变化。</p></div><Button @click="router.push('/knowledge/docs')">返回知识库</Button></div>
    <Card>
      <div class="filters">
        <label>所属系统<Select :value="library || undefined" @update:value="library = String($event || '')" :options="systems" allow-clear show-search option-filter-prop="label" placeholder="全部系统" @change="filterChanged(true)" /></label>
        <label>工程<Select :value="project || undefined" @update:value="project = String($event || '')" :options="projects" allow-clear show-search option-filter-prop="label" placeholder="全部工程" @change="filterChanged()" /></label>
        <label>主题标签<Select :value="tag || undefined" @update:value="tag = String($event || '')" :options="catalog.tags.map(t => ({label:t.value,value:t.value}))" allow-clear placeholder="全部主题" @change="filterChanged()" /></label>
      </div>
    </Card>
    <div class="file-layout"><FileBrowser :search="scope.search.value" :items="records" :selected="fileId" :total="total" :page="page" :loading="filesLoading" @select="chooseFile" @search="browse(1,$event)" @page="browse($event)" /><div>
      <Card :title="file?.name || '选择文件'">
      <div class="version-row"><label>旧版本<Select :value="oldId || undefined" @update:value="oldId = String($event || '')" :options="versions.map(v => ({ label: v.version, value: v.id }))" :disabled="!versions.length" placeholder="选择旧版本" @change="compare" /></label><Button :disabled="versions.length < 2" @click="[oldId, newId] = [newId, oldId]; compare()">交换版本</Button><label>新版本<Select :value="newId || undefined" @update:value="newId = String($event || '')" :options="versions.map(v => ({ label: v.version + (v.current ? ' · 当前' : ''), value: v.id }))" :disabled="!versions.length" placeholder="选择新版本" @change="compare" /></label><Button type="primary" :disabled="!oldId || !newId || oldId === newId" :loading="loading" @click="compare">开始对比</Button></div>
    </Card>
    <Alert v-if="fileId && versions.length < 2" type="info" show-icon message="此文件目前只有一个实际上传版本。上传相同系统、工程和文件路径的新版本后，即可进行对比。" class="notice" />
    <Spin :spinning="loading"><Card class="viewer" :title="file?.name || '内容差异'">
      <template #extra><RadioGroup v-model:value="mode" button-style="solid" size="small"><RadioButton value="side">并排</RadioButton><RadioButton value="merged">合并</RadioButton></RadioGroup></template>
      <template v-if="result"><div class="stats"><Tag color="green">新增 {{ result.stats.added }} 行</Tag><Tag color="red">删除 {{ result.stats.removed }} 行</Tag><Tag color="orange">修改 {{ result.stats.modified }} 行</Tag><span>{{ result.old }} → {{ result.new }}</span></div><div v-if="mode === 'side'" class="diff side"><div class="column-head"><strong>{{ result.old }}</strong><strong>{{ result.new }}</strong></div><div v-for="(row, index) in result.rows" :key="index" class="row" :class="row.type"><pre>{{ row.left ?? '' }}</pre><pre>{{ row.right ?? '' }}</pre></div></div><div v-else class="diff merged"><div v-for="(row,index) in result.rows" :key="index" :class="row.type"><pre v-if="row.type === 'mod'" class="del">- {{ row.left }}</pre><pre v-if="row.type === 'mod'" class="add">+ {{ row.right }}</pre><pre v-else>{{ row.type === 'add' ? '+ ' + row.right : row.type === 'del' ? '- ' + row.left : '  ' + row.left }}</pre></div></div></template>
      <Empty v-else :description="fileId ? '请选择两个不同的实际上传版本' : '先选择系统、工程，再选择要对比的文件'" />
    </Card></Spin>
    </div></div>
  </Page>
</template>
<style scoped>
.file-layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:18px;margin-top:20px;align-items:start}@media(max-width:850px){.file-layout{grid-template-columns:1fr}}.heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.heading h1{font-size:26px;margin:6px 0}.heading p,small{color:hsl(var(--muted-foreground))}.filters{display:flex;gap:16px;flex-wrap:wrap}.filters label{flex:1;min-width:160px}.filters .file-select{flex:2;min-width:280px}.filters>label,.version-row>label{display:flex;flex-direction:column;gap:8px;font-size:13px}.pages{display:flex;gap:10px;justify-content:flex-end;align-items:center;margin:12px 0 20px;color:hsl(var(--muted-foreground))}.version-row{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}.version-row label{width:200px}.viewer,.notice{margin-top:20px}.stats{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.diff{max-height:65vh;overflow:auto;border:1px solid hsl(var(--border));border-radius:8px}.diff pre{padding:4px 12px;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:monospace;font-size:12px;min-height:25px}.row,.column-head{display:grid;grid-template-columns:1fr 1fr}.column-head{position:sticky;top:0;background:hsl(var(--muted));padding:10px 12px}.row pre:first-child{border-right:1px solid hsl(var(--border))}.row.add pre:last-child,.merged .add{background:#16a34a20}.row.del pre:first-child,.merged .del{background:#dc262620}.row.mod{background:#eab30820}
</style>
