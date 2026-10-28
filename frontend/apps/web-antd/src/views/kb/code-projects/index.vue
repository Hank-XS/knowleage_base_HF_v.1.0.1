<script lang="ts" setup>
import type { ProjectChunk, ProjectFile, ProjectGraph, ProjectJob, ProjectNode } from '#/api/code-projects';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Page } from '@vben/common-ui';
import G6 from '@antv/g6';
import { Alert, Button, Card, Empty, Pagination, Select, Space, Spin, Steps, Step, Table, Tabs, TabPane, Tag, message } from 'ant-design-vue';
import { getCodeProject, getProjectChunks, getProjectGraph, getProjectSource, retryCodeProject } from '#/api/code-projects';

const route = useRoute();
const router = useRouter();
const job = ref<ProjectJob>();
const tab = ref('report');
const loading = ref(false);
const selectedFile = ref('');
const source = ref('');
const highlight = ref<[number, number]>([0, 0]);
const sourceBox = ref<HTMLElement>();
const chunks = ref<ProjectChunk[]>([]);
const chunkTotal = ref(0);
const page = ref(1);
const graphData = ref<ProjectGraph>({ nodes: [], edges: [], total: 0, truncated: false });
const graphContainer = ref<HTMLElement>();
const graphReady = ref(false);
let graph: any;
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const jobId = computed(() => String(route.params.jobId || ''));
const files = computed<ProjectFile[]>(() => job.value?.status === 'done' ? job.value.files as ProjectFile[] : []);
const fileOptions = computed(() => files.value.map((f) => ({ label: f.path, value: f.path })));
const sourceLines = computed(() => source.value.split(/\r?\n/));
const names = computed(() => Object.fromEntries(graphData.value.nodes.map((n) => [n.id, n.props.name])));
const statuses: Record<string, string> = { queued: '排队中', running: '解析中', done: '已完成', failed: '失败' };
const steps: Record<string, string> = { extract: '工程解压', parse: '结构解析', chunk: '生成切片', publish: '结果入库' };
const relations: Record<string, string> = { CONTAINS: '包含', CALLS: '调用 / 跳转', IMPORTS: '引用 Copybook', REFERENCES: '引用字段' };
const fileColumns = [
  { title: '文件路径', dataIndex: 'path', key: 'path' },
  { title: '解析情况', key: 'parse' },
  { title: '切片数', dataIndex: 'chunks' },
  { title: '操作', key: 'action' },
];
const unresolvedColumns = [
  { title: '未解析目标', dataIndex: 'name' }, { title: '关系', dataIndex: 'kind' },
  { title: '文件', dataIndex: 'path' }, { title: '行号', dataIndex: 'line' },
];
const edgeColumns = [{ title: '起点', key: 'src' }, { title: '关系', key: 'rel' }, { title: '终点', key: 'dst' }];
function stepStatus(value: string) {
  return value === 'done' ? 'finish' : value === 'failed' ? 'error' : value === 'running' ? 'process' : 'wait';
}
async function refresh() {
  clearTimeout(timer);
  const id = jobId.value;
  try {
    const data = await getCodeProject(id);
    if (disposed || id !== jobId.value) return;
    job.value = data;
    if (['queued', 'running'].includes(data.status)) timer = setTimeout(refresh, 2000);
  } catch (error: any) { message.error(error?.message || '读取任务失败'); }
}
async function retry() {
  loading.value = true;
  try { const task = await retryCodeProject(jobId.value); await router.push(`/kb/code-projects/${task.job_id}`); }
  catch (error: any) { message.error(error?.message || '重试失败'); }
  finally { loading.value = false; }
}
async function loadChunks() {
  try {
    const result = await getProjectChunks(jobId.value, selectedFile.value, page.value);
    chunks.value = result.items;
    chunkTotal.value = result.total;
  } catch (error: any) { message.error(error?.message || '读取切片失败'); }
}
async function loadSource() {
  if (!selectedFile.value) selectedFile.value = files.value[0]?.path || '';
  if (!selectedFile.value) return;
  try { source.value = (await getProjectSource(jobId.value, selectedFile.value)).content; }
  catch (error: any) { message.error(error?.message || '读取源码失败'); }
}
async function openSource(path: string, first = 0, last = 0) {
  selectedFile.value = path;
  highlight.value = [first, last];
  tab.value = 'source';
  await loadSource();
  await nextTick();
  sourceBox.value?.querySelector(`[data-line="${first}"]`)?.scrollIntoView({ block: 'center' });
}
function drawGraph() {
  if (!graphContainer.value || tab.value !== 'graph') return;
  graph?.destroy();
  graphReady.value = false;
  const textColor = getComputedStyle(graphContainer.value).color;
  graph = new G6.Graph({
    container: graphContainer.value, width: graphContainer.value.clientWidth || 900, height: 540,
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    layout: { type: 'dagre', rankdir: 'LR', nodesep: 45, ranksep: 85 },
    defaultNode: { type: 'rect', size: [160, 42], style: { radius: 6 }, labelCfg: { position: 'center', style: { fontSize: 12, fill: '#142135' } } },
    defaultEdge: { style: { endArrow: true, stroke: '#adb8c9' }, labelCfg: { style: { fontSize: 10, fill: textColor } } },
  });
  graph.on('afterlayout', () => {
    graph?.fitView(40);
    if (graph?.getZoom() > 1) graph.zoomTo(1);
    graph?.fitCenter();
    graphReady.value = true;
  });
  graph.data({
    nodes: graphData.value.nodes.map((n) => ({ id: n.id, label: n.props.name.length > 22 ? `${n.props.name.slice(0, 20)}…` : n.props.name,
      style: { fill: n.props.kind === 'file' ? '#b8c8e6' : n.label === 'Field' ? '#93d5bc' : '#82aaff' } })),
    edges: graphData.value.edges.map((e, i) => ({ id: `edge-${i}`, source: e.src, target: e.dst,
      label: relations[e.rel] || e.rel })),
  });
  graph.render();
  graph.on('node:click', (event: any) => {
    const node = graphData.value.nodes.find((n: ProjectNode) => n.id === event.item.getID());
    if (node) void openSource(node.props.path, node.props.start_line, node.props.end_line);
  });
}
async function loadGraph() {
  try {
    graphData.value = await getProjectGraph(jobId.value, selectedFile.value);
    await nextTick();
    drawGraph();
  } catch (error: any) { message.error(error?.message || '读取图谱失败'); }
}
async function changeFile() {
  page.value = 1;
  highlight.value = [0, 0];
  if (tab.value === 'source') await loadSource();
  if (tab.value === 'chunks') await loadChunks();
  if (tab.value === 'graph') await loadGraph();
}
watch(tab, async (value) => {
  if (value !== 'graph') { graph?.destroy(); graph = undefined; }
  if (value === 'chunks') await loadChunks();
  if (value === 'source') await loadSource();
  if (value === 'graph') await loadGraph();
});
watch(jobId, async () => {
  clearTimeout(timer);
  graph?.destroy(); graph = undefined;
  job.value = undefined; tab.value = 'report'; selectedFile.value = ''; source.value = '';
  await refresh();
}, { immediate: true });
onBeforeUnmount(() => { disposed = true; clearTimeout(timer); graph?.destroy(); });
</script>

<template>
  <Page>
    <Spin :spinning="loading">
      <Card>
        <template #title>{{ job?.project || '工程任务' }} <Tag>{{ job?.version }}</Tag></template>
        <template #extra><Space><Button @click="refresh">刷新</Button><Button @click="router.push('/kb/ingest')">接入任务</Button><Button @click="router.push('/knowledge/upload?mode=project')">上传工程</Button></Space></template>
        <p v-if="job">{{ job.filename }} · {{ job.library }} · <Tag>{{ statuses[job.status] }}</Tag></p>
        <Steps v-if="job" size="small" style="margin: 24px 0">
          <Step v-for="s in job.steps" :key="s.step" :title="steps[s.step] || s.step" :description="s.detail" :status="stepStatus(s.status)" />
        </Steps>
        <Alert v-if="job?.error" type="error" show-icon message="工程解析失败" :description="job.error" />
        <Button v-if="job?.status === 'failed'" style="margin-top: 16px" type="primary" @click="retry">重试解析</Button>
        <Alert v-if="job?.superseded_by" type="warning" message="这是历史快照，该工程版本已被重新上传替换。此处保留历史结果，当前检索使用新的快照。" />
        <div v-if="job?.summary" class="summary">
          <span>源码 <b>{{ job.summary.files }}</b></span><span>切片 <b>{{ job.summary.chunks }}</b></span>
          <span>节点 <b>{{ job.summary.nodes }}</b></span><span>关系 <b>{{ job.summary.edges }}</b></span>
          <span>未解析引用 <b>{{ job.summary.unresolved }}</b></span><span>跳过文件 <b>{{ job.summary.skipped }}</b></span>
        </div>
      </Card>
      <Card v-if="job?.status === 'done'" style="margin-top: 16px">
        <Tabs v-model:active-key="tab">
          <TabPane key="report" tab="解析报告">
            <Alert type="info" show-icon message="结构解析完成，不代表所有业务语义和动态调用均已解析"
              :description="`CodeGraph ${job.engine_version} · 未调用大模型 · 已建立本地基础检索，未启用语义模型`" style="margin-bottom: 16px" />
            <Table :columns="fileColumns" :data-source="files" row-key="path" :pagination="{ pageSize: 10 }">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'parse'">
                  <Tag :color="record.indexed && record.structural_chunks && (!record.errors || record.errors === '[]') ? 'green' : 'orange'">{{ !record.indexed ? '未进入索引' : !record.structural_chunks ? '文件切片（结构不足）' : record.errors && record.errors !== '[]' ? '存在解析异常' : '已提取结构' }}</Tag>
                  <span v-if="record.errors && record.errors !== '[]'">{{ record.errors }}</span>
                </template>
                <Button v-else-if="column.key === 'action'" type="link" @click="openSource(record.path)">查看源码</Button>
              </template>
            </Table>
            <h3>未解析引用（{{ job.unresolved?.length || 0 }}）</h3>
            <Table :columns="unresolvedColumns" :data-source="job.unresolved" :pagination="{ pageSize: 8 }" size="small" />
            <h3>跳过文件（{{ job.skipped.length }}）</h3>
            <Table :columns="[{ title: '路径', dataIndex: 'path' }, { title: '原因', dataIndex: 'reason' }]" :data-source="job.skipped" row-key="path" :pagination="{ pageSize: 8 }" size="small" />
          </TabPane>
          <TabPane key="source" tab="工程源码">
            <Select v-model:value="selectedFile" show-search :options="fileOptions" style="width: min(100%, 700px); margin-bottom: 16px" @change="changeFile" />
            <div ref="sourceBox" class="source-box"><div v-for="(line, index) in sourceLines" :key="index" :data-line="index + 1" :class="{ highlighted: index + 1 >= highlight[0] && index + 1 <= highlight[1] }"><span class="line-number">{{ index + 1 }}</span><code>{{ line || ' ' }}</code></div></div>
          </TabPane>
          <TabPane key="chunks" tab="结构切片">
            <Select v-model:value="selectedFile" show-search :options="[{ label: '全部文件', value: '' }, ...fileOptions]" style="width: min(100%, 700px); margin-bottom: 16px" @change="changeFile" />
            <Card v-for="chunk in chunks" :key="chunk.id" :title="chunk.title" style="margin-bottom: 12px" size="small">
              <template #extra><Button type="link" @click="openSource(chunk.path, chunk.start_line, chunk.end_line)">定位源码</Button></template>
              <p>{{ chunk.path }} · L{{ chunk.start_line }}–L{{ chunk.end_line }}</p><pre class="chunk-code">{{ chunk.text }}</pre>
            </Card>
            <Empty v-if="!chunks.length" description="暂无切片" />
            <Pagination v-model:current="page" :total="chunkTotal" :page-size="20" :show-size-changer="false" @change="loadChunks" />
          </TabPane>
          <TabPane key="graph" tab="代码关系图">
            <Select v-model:value="selectedFile" show-search :options="[{ label: '整个工程', value: '' }, ...fileOptions]" style="width: min(100%, 700px); margin-bottom: 16px" @change="changeFile" />
            <p>点击节点可定位源码；可拖拽、缩放。CALLS 包含静态调用和段落跳转。</p>
            <Alert v-if="graphData.truncated" type="warning" message="当前仅展示部分节点或关系，请选择具体文件缩小范围。" />
            <div ref="graphContainer" class="graph-box" :data-ready="graphReady"></div>
            <Table :columns="edgeColumns" :data-source="graphData.edges" :pagination="{ pageSize: 10 }" size="small">
              <template #bodyCell="{ column, record }"><template v-if="column.key === 'src'">{{ names[record.src] }}</template><template v-else-if="column.key === 'dst'">{{ names[record.dst] }}</template><template v-else-if="column.key === 'rel'">{{ relations[record.rel] || record.rel }}</template></template>
            </Table>
          </TabPane>
        </Tabs>
      </Card>
    </Spin>
  </Page>
</template>

<style scoped>
.summary { display: flex; flex-wrap: wrap; gap: 28px; padding-top: 20px; }
.summary b { font-size: 24px; margin-left: 8px; }
.source-box { max-height: 650px; overflow: auto; background: #142135; color: #dce6f4; padding: 16px 0; font: 13px/1.8 Consolas, monospace; }
.source-box > div { display: flex; white-space: pre; min-width: max-content; }
.line-number { width: 65px; flex: 0 0 65px; color: #8a9bb4; text-align: right; padding-right: 20px; user-select: none; }
.highlighted { background: #384b24; }
.chunk-code { white-space: pre; overflow: auto; max-height: 400px; padding: 16px; background: #142135; color: #dce6f4; }
.graph-box { height: 540px; border: 1px solid #dce3ed; border-radius: 8px; margin: 12px 0; }
h3 { margin: 20px 0 12px; font-weight: 600; }
</style>
