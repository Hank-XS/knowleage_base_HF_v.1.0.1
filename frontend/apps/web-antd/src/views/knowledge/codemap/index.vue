<script lang="ts" setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Empty, RadioButton, RadioGroup, Select, Spin, Tag, message } from 'ant-design-vue';
import { getKmDoc } from '#/api/kb';
import { getFileMapping, getFileVersions, type FileVersion } from '#/api/knowledge-browse';
import { useFileScope } from '../file-scope';

defineOptions({ name: 'KnowledgeCodeMap' });
const route = useRoute(); const router = useRouter(); const scope = useFileScope();
const { library, project, tag, catalog, fileId, file, systems, projects, files } = scope;
const direction = ref('code2doc'); const versions = ref<FileVersion[]>([]); const versionId = ref('');
const data = ref<Awaited<ReturnType<typeof getFileMapping>>>(); const loading = ref(false); let sequence = 0;
const extra = () => ({ asset_type: direction.value === 'code2doc' ? 'code' : 'document' });
async function loadMap() {
  const id = ++sequence;
  if (!fileId.value || !versionId.value) { data.value = undefined; loading.value = false; return; }
  loading.value = true;
  try { const response = await getFileMapping(fileId.value, direction.value, versionId.value); if (id === sequence) data.value = response; }
  catch (e: any) { message.error(e.response?.data?.message || e.message || '读取引用关系失败'); }
  finally { if (id === sequence) loading.value = false; }
}
async function selectFile() {
  sequence++; loading.value = false; data.value = undefined; versions.value = []; versionId.value = ''; const requested = fileId.value;
  if (!requested) return;
  try { const [doc, rows] = await Promise.all([getKmDoc(requested), getFileVersions(requested)]); if (requested !== fileId.value) return; file.value = doc; versions.value = rows; versionId.value = rows.find(v => v.current)?.id || rows.at(-1)?.id || ''; await loadMap(); }
  catch (e: any) { message.error(e.message || '读取文件失败'); }
}
async function filterChanged(system = false) { sequence++; loading.value = false; data.value = undefined; versions.value = []; versionId.value = ''; await scope.reset(system, extra()); }
function openFile(id: string, version: string) { router.push({ path: '/knowledge/chunk', query: { doc: id, version } }); }
async function refresh() { await scope.initialize(route.query, extra()); if (fileId.value) await selectFile(); }
onMounted(refresh); watch(() => route.fullPath, () => { if (route.path === '/knowledge/codemap') void refresh(); }); onBeforeUnmount(() => { sequence++; });
</script>
<template>
  <Page>
    <div class="heading"><div><small>内容管理 / 引用追踪</small><h1>代码文档映射</h1><p>按系统和工程查找代码与文档中的程序名、文件名引用。</p></div><Button @click="router.push('/knowledge/docs')">返回知识库</Button></div>
    <Card><RadioGroup v-model:value="direction" button-style="solid" @change="filterChanged()"><RadioButton value="code2doc">代码 → 文档</RadioButton><RadioButton value="doc2code">文档 → 代码</RadioButton></RadioGroup>
      <div class="filters"><label>所属系统<Select :value="library || undefined" @update:value="library = String($event || '')" :options="systems" allow-clear show-search option-filter-prop="label" placeholder="全部系统" @change="filterChanged(true)" /></label><label>工程<Select :value="project || undefined" @update:value="project = String($event || '')" :options="projects" allow-clear show-search option-filter-prop="label" placeholder="全部工程" @change="filterChanged()" /></label><label>主题标签<Select :value="tag || undefined" @update:value="tag = String($event || '')" :options="catalog.tags.map(t => ({label:t.value,value:t.value}))" allow-clear placeholder="全部主题" @change="filterChanged()" /></label><label class="file-select">{{ direction === 'code2doc' ? '代码文件' : '文档文件' }}<Select :value="fileId || undefined" @update:value="fileId = String($event || '')" :options="files" :loading="scope.loading.value" show-search :filter-option="false" :placeholder="direction === 'code2doc' ? '搜索代码文件或 Copybook' : '搜索文档名称'" @search="scope.searchFiles($event, extra())" @popup-scroll="scope.loadMore($event, extra())" @change="selectFile" /></label><label>版本<Select :value="versionId || undefined" @update:value="versionId = String($event || '')" :options="versions.map(v => ({ label: v.version, value: v.id }))" :disabled="!versions.length" placeholder="选择版本" @change="loadMap" /></label></div>

    </Card>
    <Alert class="notice" type="info" show-icon message="引用根据文档中的程序名和文件名匹配。代码只关联同系统下的本工程文档和系统通用资料；这类引用仍需业务确认。" />
    <Spin :spinning="loading"><div v-if="data" class="panes"><Card :title="data.file.label"><template #extra><Tag>{{ data.file.version }}</Tag><Button type="link" @click="openFile(data.file.key, data.file.version)">查看原文与切片</Button></template><pre class="content">{{ data.file.content }}</pre></Card><Card :title="`${direction === 'code2doc' ? '关联文档' : '关联代码'} · ${data.relatedDocs.length}`"><div v-for="item in data.relatedDocs" :key="item.id" class="related"><strong>{{ item.name }}</strong><p>{{ item.section }}</p><Tag>{{ item.project || '系统通用' }}</Tag><Tag>{{ item.version }}</Tag><Button type="link" @click="openFile(item.id, item.version)">查看原文与切片</Button><Button v-if="direction === 'doc2code'" type="link" @click="router.push({ path: '/kb/graph', query: { doc: item.id } })">代码关系图</Button></div><Empty v-if="!data.relatedDocs.length" :description="direction === 'code2doc' ? '当前范围没有文档引用此程序或文件，可上传关联说明文档后再查看' : '文档中未匹配到当前工程的程序名或文件名'" /></Card></div><Card v-else class="notice"><Empty :description="`先选择系统、工程，再选择${direction === 'code2doc' ? '代码文件' : '文档'}`" /></Card></Spin>
  </Page>
</template>
<style scoped>
.heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.heading h1{font-size:26px;margin:6px 0}.heading p,small{color:hsl(var(--muted-foreground))}.filters{display:flex;gap:16px;flex-wrap:wrap;margin-top:20px}.filters label{display:flex;flex:1;flex-direction:column;gap:8px;min-width:150px;font-size:13px}.filters .file-select{flex:2;min-width:280px}.pages{display:flex;gap:10px;justify-content:flex-end;align-items:center;margin-top:14px;color:hsl(var(--muted-foreground))}.notice{margin-top:20px}.panes{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;margin-top:20px}.content{max-height:65vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;background:hsl(var(--muted));padding:16px;border-radius:8px;font-size:12px}.related{padding:16px;border:1px solid hsl(var(--border));border-radius:8px;margin-bottom:12px}.related strong,.related p{overflow-wrap:anywhere}.related p{color:hsl(var(--muted-foreground));margin:10px 0}@media(max-width:1000px){.panes{grid-template-columns:1fr}}
</style>
