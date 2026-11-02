<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import { AutoComplete, Button, Card, Form, FormItem, Input, Modal, Progress, RadioButton, RadioGroup, Select, Steps, Tag, UploadDragger, message } from 'ant-design-vue';
import { createSystem, getCatalog, type CatalogOptions } from '#/api/catalog';
import { uploadKmDoc } from '#/api/kb';
import { getCodeProject, uploadCodeProject } from '#/api/code-projects';
defineOptions({ name: 'KnowledgeUpload' });
const route = useRoute(); const router = useRouter();
const mode = ref(route.query.mode === 'project' ? 'project' : 'document');
const catalog = ref<CatalogOptions>({ libraries: [], projects: [], purposes: [], tags: [] });
const library = ref(String(route.query.kb || '')); const project = ref(''); const purpose = ref('reference');
const version = ref('v1.0'); const tags = ref<string[]>([]); const encoding = ref('utf-8');
const files = ref<any[]>([]); const busy = ref(false); const results = ref<any[]>([]);
const newSystem = ref(''); const systemModal = ref(false); const creating = ref(false);
let disposed = false;
const systems = computed(() => catalog.value.libraries.flatMap(l => [{ label: l.title, value: l.key }, ...(l.children || []).map(c => ({ label: `${l.title} / ${c.title}`, value: c.key }))]));
const projects = computed(() => catalog.value.projects.filter(p => p.library === library.value).map(p => ({ label: p.name, value: p.name })));
const systemTitle = computed(() => systems.value.find(s => s.value === library.value)?.label || '未选择所属系统');
const purposeTitle = computed(() => catalog.value.purposes.find(p => p.value === purpose.value)?.label || '参考资料');
const completed = computed(() => results.value.filter(r => ['done', 'failed'].includes(r.status)).length);
async function loadCatalog() { catalog.value = await getCatalog(); }
async function addSystem() {
  if (!newSystem.value.trim()) return;
  creating.value = true;
  try { const r = await createSystem(newSystem.value.trim()); await loadCatalog(); library.value = r.key; project.value = ''; systemModal.value = false; newSystem.value = ''; }
  catch (e: any) { message.error(e.message || '创建失败'); } finally { creating.value = false; }
}
function switchMode() { files.value = []; project.value = ''; results.value = []; }
const stepNames: Record<string,string> = { extract: '工程解压', parse: '结构解析', chunk: '切片整理', publish: '结果入库' };
function bytes(value: number) { return value < 1024 * 1024 ? `${Math.round(value / 1024)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
function updateJob(result: any, job: any) { result.steps = job.steps || []; const active = result.steps.find((s: any) => s.status === 'running'); result.stage = job.status === 'queued' ? '等待工程解析' : active ? stepNames[active.step] : job.status === 'done' ? '入库完成' : '正在处理工程'; }
async function submit() {
  if (!library.value || !version.value.trim() || mode.value === 'project' && !project.value.trim()) { message.warning('请填写所属系统、版本和工程名称'); return; }
  const selected = files.value.map(f => f.originFileObj || f).filter(f => f instanceof File);
  if (!selected.length) { message.warning('请先选择文件'); return; }
  if (new Set(selected.map(f => f.name.toLowerCase())).size !== selected.length) { message.warning('本次选择包含同名文件，请分别上传并指定版本'); return; }
  if (tags.value.length > 12 || tags.value.some(t => t.trim().length > 32)) { message.warning('最多添加 12 个主题标签，每个不超过 32 个字符'); return; }
  for (const file of selected) {
    const valid = mode.value === 'project' ? /\.zip$/i.test(file.name) : /\.(docx|pdf|md)$/i.test(file.name);
    if (!valid || file.size > (mode.value === 'project' ? 50 : 25) * 1024 * 1024) { message.error(`文件格式或大小不符合要求：${file.name}`); return; }
  }
  busy.value = true; results.value = selected.map(f => ({ name: f.name, status: 'waiting', uploadPercent: 0, loaded: 0, total: f.size, stage: '等待上传', steps: [] }));
  try {
    for (const [i, file] of selected.entries()) {
      const r = results.value[i]!; r.status = 'processing'; r.stage = '正在上传文件'; const data = new FormData();
      const progress = (event: { loaded: number; total?: number }) => { r.loaded = event.loaded; r.total = event.total || file.size; r.uploadPercent = Math.min(100, Math.round(event.loaded / Math.max(1, r.total) * 100)); if (r.uploadPercent === 100) r.stage = '上传完成，正在解析并入库'; };
      data.append('file', file); data.append('version', version.value.trim()); data.append('project', project.value.trim()); data.append('tags', JSON.stringify(tags.value));
      try {
        if (mode.value === 'project') {
          data.append('library', library.value); data.append('encoding', encoding.value);
          let job = await uploadCodeProject(data, progress); r.id = job.job_id; updateJob(r, job);
          while (!disposed && ['queued', 'running'].includes(job.status)) { await new Promise(resolve => setTimeout(resolve, 1000)); if (!disposed) { job = await getCodeProject(r.id); updateJob(r, job); } }
          if (disposed) return;
          if (job.status === 'failed') throw new Error(job.error || '解析失败');
        } else {
          data.append('library_key', library.value); data.append('purpose', purpose.value); data.append('security', 'internal');
          const doc = await uploadKmDoc(data, progress); r.id = doc.id; r.warnings = (doc as any).warnings || [];
        }
        r.status = 'done'; r.uploadPercent = 100; r.stage = '入库完成';
      } catch (e: any) { r.status = 'failed'; r.error = e.response?.data?.message || e.message || '处理失败'; }
    }
    if (results.value.every(r => r.status === 'done')) { files.value = []; message.success('资料已入库'); }
    await loadCatalog();
  } finally { busy.value = false; }
}
async function refresh() { if (route.query.kb && route.query.kb !== library.value) { library.value = String(route.query.kb); project.value = ''; } if (route.query.mode === 'project' && mode.value !== 'project' && !busy.value) { mode.value = 'project'; switchMode(); } await loadCatalog(); }
onMounted(refresh);
watch(() => route.fullPath, () => { if (route.path === '/knowledge/upload') void refresh(); });
onBeforeUnmount(() => { disposed = true; });
</script>
<template>
  <Page content-class="upload-page">
    <div class="heading"><div><small>内容管理 / 资料接入</small><h1>上传资料</h1><p>先确定资料归属，让每一份文档和工程都能被找到。</p></div><Button @click="router.push('/knowledge/docs')">返回知识库</Button></div>
    <RadioGroup v-model:value="mode" button-style="solid" :disabled="busy" @change="switchMode"><RadioButton value="document">文档资料</RadioButton><RadioButton value="project">代码工程 ZIP</RadioButton></RadioGroup>
    <div class="upload-layout"><div>
      <Card :title="mode === 'document' ? '选择文档' : '选择完整工程'">
        <UploadDragger v-model:file-list="files" :multiple="mode === 'document'" :max-count="mode === 'project' ? 1 : 20" :disabled="busy" :accept="mode === 'project' ? '.zip' : '.docx,.pdf,.md'" :before-upload="() => false">
          <div class="drop-icon">↑</div><h3>拖拽文件到这里，或点击选择</h3><p>{{ mode === 'project' ? 'ZIP · 不超过 50 MB' : 'DOCX / 文本型 PDF / Markdown · 单文件不超过 25 MB' }}</p>
        </UploadDragger>
        <div class="explain"><strong>{{ mode === 'document' ? '保留文档结构与上下文' : '保留完整工程目录' }}</strong><p>{{ mode === 'document' ? '按章节、段落、列表和表格整理切片，同时保存原文件。扫描型 PDF 请先进行 OCR。' : '一起打包主程序和 Copybook，保留目录。分析完成后，可在知识库列表、切片查看和图谱中找到。' }}</p></div>
      </Card>
      <Card v-if="results.length" title="本次上传" class="result-card"><p>已处理 {{ completed }} / {{ results.length }} 个文件</p><Progress :percent="Math.round(completed / results.length * 100)" :status="results.some(r => r.status === 'failed') ? 'exception' : busy ? 'active' : 'success'" /><div v-for="r in results" :key="r.name" class="result-row"><div class="result-body"><div class="result-title"><strong>{{ r.name }}</strong><Tag :color="r.status === 'done' ? 'green' : r.status === 'failed' ? 'red' : 'blue'">{{ ({ done: '已入库', failed: '失败', waiting: '等待上传', processing: r.stage } as any)[r.status] }}</Tag></div><div class="transfer"><span>文件上传 {{ r.uploadPercent }}%</span><small>{{ bytes(r.loaded) }} / {{ bytes(r.total) }}</small></div><Progress :percent="r.uploadPercent" :show-info="false" :status="r.status === 'failed' ? 'exception' : r.uploadPercent < 100 ? 'active' : 'normal'" size="small" /><Steps v-if="r.steps.length" size="small" class="parse-steps" :items="r.steps.map((s: any) => ({ title: stepNames[s.step] || s.step, status: s.status === 'done' ? 'finish' : s.status === 'failed' ? 'error' : s.status === 'running' ? 'process' : 'wait' }))" /><p v-if="r.error" class="error">{{ r.error }}</p><p v-for="w in r.warnings" :key="w">{{ w }}</p><Button v-if="r.status === 'done'" type="link" @click="router.push(mode === 'document' ? { path: '/knowledge/chunk', query: { doc: r.id } } : { path: '/knowledge/docs', query: { project, kb: library } })">查看结果</Button><Button v-if="r.id && mode === 'project' && r.status === 'failed'" type="link" @click="router.push(`/kb/code-projects/${r.id}`)">查看处理详情</Button></div></div></Card>
    </div>
    <Card title="资料归属与分类" class="metadata"><Form layout="vertical" :disabled="busy">
      <FormItem label="所属系统 / 知识库" required><div class="system-picker"><Select :value="library || undefined" @update:value="library = String($event || '')" :options="systems" show-search option-filter-prop="label" placeholder="选择系统" @change="project = ''" /><Button @click="systemModal = true">新建</Button></div></FormItem>
      <FormItem :label="mode === 'project' ? '工程名称' : '关联工程'" :required="mode === 'project'"><AutoComplete v-if="mode === 'project'" v-model:value="project" :options="projects" placeholder="选择已有工程，或输入新名称" /><Select v-else v-model:value="project" :options="[{ label: '系统通用资料', value: '' }, ...projects]" :disabled="!library" show-search option-filter-prop="label" /></FormItem>
      <FormItem v-if="mode === 'document'" label="资料用途" required><Select v-model:value="purpose" :options="catalog.purposes" /></FormItem>
      <FormItem label="版本" required><Input v-model:value="version" :maxlength="32" placeholder="例如 v1.0 或 2026-10" /><p class="help">{{ mode === 'project' ? '同系统、工程名称沿用版本记录。解析成功后切换为当前版本，同版本重传会替换该版本。' : '同系统、工程下的同名文件沿用版本记录。新版本保留历史，同版本重传会替换该版本。' }}</p></FormItem>
      <FormItem label="主题标签"><Select v-model:value="tags" mode="tags" :max-tag-count="4" :token-separators="[',', '，']" :options="catalog.tags.map(t => ({ label: t.value, value: t.value }))" placeholder="选择已有标签，或输入后按回车" /><p class="help">可自定义，无固定预设。随资料成功入库后，会加入已有标签供下次选择。建议统一业务用词，最多 12 个。格式和语言自动识别。</p></FormItem>
      <FormItem v-if="mode === 'project'" label="源码编码"><Select v-model:value="encoding" :options="[{ label: 'UTF-8', value: 'utf-8' }, { label: 'GB18030 / GBK', value: 'gb18030' }]" /></FormItem>
      <div class="preview"><small>归档位置</small><p>{{ systemTitle }} / {{ project || '系统通用' }}</p><Tag>{{ mode === 'project' ? '代码工程' : purposeTitle }}</Tag><Tag>{{ version || '待填写版本' }}</Tag></div>
      <Button type="primary" size="large" block :loading="busy" @click="submit">{{ busy ? '正在处理资料' : '上传并入库' }}</Button>
    </Form></Card></div>
    <Modal v-model:open="systemModal" title="新建系统 / 知识库" :confirm-loading="creating" @ok="addSystem"><p>使用业务系统名称，后续文档和工程将归入此系统。</p><Input v-model:value="newSystem" :maxlength="100" placeholder="例如：账户核心系统" @press-enter="addSystem" /></Modal>
  </Page>
</template>
<style scoped>
.heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.heading small,.heading p,.help{color:#64748b}.heading h1{font-size:26px;margin:6px 0}.upload-layout{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:24px;margin-top:20px}.drop-icon{font-size:40px;color:#2563eb;margin:25px 0 10px}.explain,.preview{padding:18px;background:hsl(var(--muted));border-radius:8px;margin:24px 0 0}.explain p{color:#64748b;line-height:1.8;margin:8px 0 0}.system-picker{display:flex;gap:8px}.system-picker .ant-select{flex:1;min-width:0}.help{font-size:12px;margin:7px 0 0}.preview{margin:0 0 20px}.preview p{font-weight:600;overflow-wrap:anywhere}.result-card{margin-top:20px}.result-row{display:flex;gap:12px;align-items:center;padding:14px 0;border-bottom:1px solid #eef2f6}.result-title,.transfer{display:flex;justify-content:space-between;gap:12px;align-items:center}.transfer{font-size:12px;margin-top:12px}.parse-steps{margin:16px 0}.result-row>div{flex:1;min-width:0}.error{color:#dc2626}@media(max-width:1000px){.upload-layout{grid-template-columns:1fr}}
</style>
