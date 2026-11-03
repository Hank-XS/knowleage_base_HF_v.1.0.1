<script lang="ts" setup>
import type { GraphEdge, GraphNode } from '#/api/kb';

import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue';

import { Page } from '@vben/common-ui';
import { useRoute, useRouter } from 'vue-router';
import { getKmDoc } from '#/api/kb';
import { getProjectVersions } from '#/api/knowledge-browse';
import { useFileScope } from '#/views/knowledge/file-scope';
import { confirmCleanup } from '#/views/knowledge/cleanup';

import {
  Button as AButton,
  RadioGroup, RadioButton,
  Card,
  Checkbox as ACheckbox,
  Alert as AAlert,
  Col as ACol,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Drawer as ADrawer,
  Empty as AEmpty,
  Input as AInput,
  Row as ARow,
  Select as ASelect,
  Spin as ASpin,
  TabPane as ATabPane,
  Table as ATable,
  Tabs as ATabs,
  Tag as ATag,
  message,
} from 'ant-design-vue';

import { graphStruct } from '#/api/kb';

defineOptions({ name: 'KbGraph' });

const LABEL_COLORS: Record<string, string> = {
  Program: '#4158D0', Procedure: '#9B6FFF',
  Document: '#269A99', DocumentSection: '#6DC8EC', CodeFile: '#9FB1FC',
  System: '#5B8FF9',
  SubSystem: '#5AD8A6',
  FunctionPoint: '#F6BD16',
  BusinessProcess: '#E8684A',
  BusinessRule: '#6DC8EC',
  ErrorCode: '#FF9D4D',
  CardType: '#9270CA',
  Interface: '#269A99',
  CodeUnit: '#5D7092',
  CopyBook: '#21A79B',
  TechComponent: '#BFBFBF',
  DataTable: '#FF85C0',
  MessageFormat: '#A0D911',
  Field: '#C2C8D0',
  Tag: '#FAAD14',
};
const LABEL_NAMES: Record<string, string> = {
  Program: '程序', Procedure: '段落 / SECTION',
  Document: '文档', DocumentSection: '文档章节', CodeFile: '代码文件',
  System: '系统',
  SubSystem: '子系统',
  FunctionPoint: '功能点',
  BusinessProcess: '业务流程',
  BusinessRule: '业务规则',
  ErrorCode: '错误码',
  CardType: '卡种',
  Interface: '接口',
  CodeUnit: '代码单元',
  CopyBook: 'Copybook 引用',
  TechComponent: '技术组件',
  DataTable: '数据表',
  MessageFormat: '报文格式',
  Field: '字段',
  Tag: '标签',
};
const REL_NAMES: Record<string, string> = {
  CONTAINS: '包含', IMPORTS: '引用 Copybook', REFERENCES: '引用',
  PART_OF: '属于',
  REALIZED_BY: '实现于',
  CALLS: '调用', MENTIONS: '提及',
  READS: '读',
  WRITES: '写',
  IMPLEMENTED_BY: '实现为',
  USES: '使用',
  HAS_FIELD: '含字段',
  MAPPED_FROM: '映射自',
  RAISED_IN: '出现于',
  ALIAS_OF: '别名于',
  FIXED: '修复',
  TAGGED: '打标',
  DEPLOYED_ON: '部署于',
};

const route = useRoute(); const router = useRouter();
const scope = useFileScope();
const { catalog, library, project: projectFilter, tag: tagFilter, fileId, file, files, systems, projects } = scope;
const versionFilter = ref(String(route.query.version || ''));
const versionOptions = ref<{ label: string; value: string }[]>([]);
const neighbors = ref(true); const showRelations = ref(true);
const canClean = computed(() => !!fileId.value || !!(library.value && projectFilter.value));
const view = ref('files'); const crossSystem = ref(false);
const relationOpen = ref(false); const relationDetail = ref<any>();
const detailFilter = ref(false);
const truncated = ref(false);
const loading = ref(true);
const allNodes = shallowRef<GraphNode[]>([]);
const allEdges = shallowRef<GraphEdge[]>([]);
const stats = reactive({ edges: 0, nodes: 0, cross_project: 0, by_label: {} as Record<string, number> });

const labelOptions = ref<{ label: string; value: string }[]>([]);
const selectedLabels = ref<string[]>([]);
const keyword = ref('');

const activeTab = ref('graph');
const detailOpen = ref(false);
const detail = ref<{ node: GraphNode; inEdges: GraphEdge[]; outEdges: GraphEdge[] } | null>(null);
const nameOf = ref<Record<string, { label: string; name: string }>>({});

const containerRef = ref<HTMLElement>();
const hoverTip = ref<{ name: string; type: string; x: number; y: number }>();
let graph: any = null;
let requestSequence = 0;
let renderSequence = 0;
let layoutWorker: Worker | undefined;
const positions = new Map<string, { x: number; y: number }>();
const layoutTasks = new Map<number, (value: any) => void>();
let layoutRequest = 0;
const loadedText = computed(() => loading.value || truncated.value ? `已加载 ${allNodes.value.length} / ${stats.nodes} 个节点，${allEdges.value.length} / ${stats.edges} 条关系` : `已加载全部 ${allNodes.value.length} 个节点和 ${allEdges.value.length} 条关系`);
let labelsVisible = false;
let nodeLabelsVisible = false;

function calculatePositions(nodes: GraphNode[], edges: GraphEdge[]): Promise<Record<string, { x: number; y: number }>> {
  const fallback = () => Object.fromEntries(nodes.map((n, i) => [n.id, { x: (i % 30) * 160, y: Math.floor(i / 30) * 100 }]));
  return new Promise(resolve => {
    try {
      layoutWorker ||= new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' });
      layoutWorker.onmessage = event => { const task = layoutTasks.get(event.data.request); layoutTasks.delete(event.data.request); task?.(event.data.positions); };
      layoutWorker.onerror = () => { for (const task of layoutTasks.values()) task(undefined); layoutTasks.clear(); layoutWorker?.terminate(); layoutWorker = undefined; };
      const request = ++layoutRequest;
      const timer = window.setTimeout(() => { layoutTasks.delete(request); resolve(fallback()); }, 8000);
      layoutTasks.set(request, value => { window.clearTimeout(timer); resolve(value || fallback()); });
      layoutWorker.postMessage({ request, nodes: nodes.map(n => ({ id: n.id })), edges: edges.map(e => ({src:e.src,dst:e.dst})) });
    } catch { resolve(fallback()); }
  });
}

function updateRelationLabels() {
  if (!graph) return;
  const visible = showRelations.value && (allNodes.value.length < 250 || graph.getZoom() >= .35);
  const nodeVisible = allNodes.value.length < 600 || graph.getZoom() >= .25;
  if (labelsVisible === visible && nodeLabelsVisible === nodeVisible) return;
  labelsVisible = visible;
  graph.setAutoPaint(false);
  for (const item of graph.getEdges()) graph.updateItem(item, { label: visible ? item.getModel().relationText : '' });
  if (nodeLabelsVisible !== nodeVisible) for (const item of graph.getNodes()) graph.updateItem(item, { label: nodeVisible ? item.getModel().nodeText : '' });
  nodeLabelsVisible = nodeVisible;
  graph.setAutoPaint(true); graph.paint();
}

const tripleColumns = [
  { title: '头实体', key: 'src', width: 220 },
  { title: '关系', dataIndex: 'rel', key: 'rel', width: 110 },
  { title: '尾实体', key: 'dst', width: 220 },
];

function buildNameIndex() {
  const idx: Record<string, { label: string; name: string }> = {};
  for (const n of allNodes.value) idx[n.id] = { label: n.label, name: n.name };
  nameOf.value = idx;
}

function currentData() {
  const kw = keyword.value.trim().toLowerCase();
  let nodes = allNodes.value.filter((n) => selectedLabels.value.includes(n.label));
  let nodeIds = new Set(nodes.map((n) => n.id));
  let edges = allEdges.value.filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst));

  if (kw) {
    const hit = nodes.filter((n) => n.name.toLowerCase().includes(kw) || n.id.toLowerCase().includes(kw));
    const hitIds = new Set(hit.map((n) => n.id));
    const keep = new Set(hitIds);
    for (const e of edges) {
      if (hitIds.has(e.src)) keep.add(e.dst);
      if (hitIds.has(e.dst)) keep.add(e.src);
    }
    nodes = nodes.filter((n) => keep.has(n.id));
    nodeIds = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst));
  }
  return { nodes, edges };
}

async function renderGraph() {
  const render = ++renderSequence;
  const container = containerRef.value;
  if (!container || activeTab.value !== 'graph') return;
  const { nodes, edges } = currentData();
  const [module, layout] = await Promise.all([import('@antv/g6'), calculatePositions(nodes, edges)]);
  if (render !== renderSequence || !container.isConnected) return;
  const G6 = module.default;
  hoverTip.value = undefined; container.style.cursor = '';
  const previous = graph; graph = undefined; previous?.destroy(); container.replaceChildren();
  const styles = getComputedStyle(document.documentElement);
  const background = `hsl(${styles.getPropertyValue('--background').trim() || '0 0% 100%'})`;
  const foreground = `hsl(${styles.getPropertyValue('--foreground').trim() || '215 25% 27%'})`;
  const groupedEdges = new Map<string, { source: string; target: string; relations: string[]; evidence: any[]; evidenceTotal: number; cross: boolean }>();
  const nodeIndex = new Map(allNodes.value.map(node => [node.id, node]));
  for (const edge of edges) {
    const key = JSON.stringify([edge.src, edge.dst]);
    const group = groupedEdges.get(key) || { source: edge.src, target: edge.dst, relations: [], evidence: [], evidenceTotal: 0, cross: false };
    if (!group.relations.includes(edge.rel)) group.relations.push(edge.rel);
    const props = (edge as any).props || {}; group.cross ||= !!props.cross_project; group.evidenceTotal += props.occurrences || 1; for (const evidence of (props.evidence_items || [props]).slice(0, 20)) group.evidence.push({ ...evidence, rel:edge.rel, source:nodeIndex.get(edge.src), target:nodeIndex.get(edge.dst) });
    groupedEdges.set(key, group);
  }
  const instance = new G6.Graph({
    container, renderer: 'canvas', animate: false, pixelRatio: 1,
    height: Math.max(360, container.clientHeight || 480),
    width: container.clientWidth || 900,
    modes: { default: [{ type: 'drag-canvas', enableOptimize: true }, { type: 'zoom-canvas', enableOptimize: true }, 'drag-node'] },
    defaultNode: {
      type: 'circle',
      size: 26,
      labelCfg: { position: 'bottom', style: { fontSize: 11, fill: foreground } },
    },
    defaultEdge: {
      style: { endArrow: true, stroke: '#c5cdd8', lineWidth: 1 },
      labelCfg: { autoRotate: true, style: { fontSize: 11, fill: foreground, background: { fill: background, padding: [2, 4], radius: 2 } } },
    },
    nodeStateStyles: {
      hover: { stroke: '#1677ff', lineWidth: 3 },
      selected: { stroke: '#f5222d', lineWidth: 2.5 },
    },
  });
  graph = instance;
  // Root viewport transforms invalidate dirty-rectangle bounds; redraw the canvas as a whole.
  instance.get('canvas').set('localRefresh', false);
  labelsVisible = showRelations.value && nodes.length < 250;
  nodeLabelsVisible = nodes.length < 600;
  let userMoved = false;
  const fit = () => requestAnimationFrame(() => {
    if (graph !== instance || userMoved) return;
    if (!instance.getNodes().length) return;
    instance.fitView(40);
    if (instance.getZoom() > 1) { instance.zoomTo(1); instance.fitCenter(); }
  });
  instance.on('afterlayout', fit); instance.on('afterrender', fit);
  const stopLayout = () => { hoverTip.value = undefined; userMoved = true; instance.get('layoutController')?.layoutMethods?.forEach((layout: any) => layout.stop?.()); };
  instance.on('canvas:dragstart', stopLayout); instance.on('node:dragstart', stopLayout);
  instance.on('edge:click', (event: any) => { relationDetail.value = event.item.getModel(); relationOpen.value = true; });
  graph.data({
    nodes: nodes.map((n) => ({
      id: n.id,
      ...(positions.get(n.id) || layout[n.id]),
      nodeText: view.value === 'files' ? `${n.name.split('/').pop()}${n.props.project ? '\n' + n.props.project : ''}` : n.name.length > 18 ? `${n.name.slice(0,17)}…` : n.name,
      label: nodeLabelsVisible ? (view.value === 'files' ? `${n.name.split('/').pop()}${n.props.project ? '\n' + n.props.project : ''}` : n.name.length > 18 ? `${n.name.slice(0,17)}…` : n.name) : '',
      size: ['FunctionPoint', 'Interface'].includes(n.label) ? 36 : 26,
      style: { fill: view.value === 'files' ? projectColor(n.props.library + '/' + (n.props.project || '系统通用')) : LABEL_COLORS[n.label] ?? '#9099A6', ...((n as any).external ? { lineDash: [4, 3], stroke: foreground, lineWidth: 1.5 } : {}) },
    })),
    edges: [...groupedEdges.values()].map((e, i) => ({
      id: `edge-${i}`,
      source: e.source,
      target: e.target,
      type: e.source === e.target ? 'loop' : groupedEdges.has(JSON.stringify([e.target, e.source])) ? 'quadratic' : 'line',
      curveOffset: 30,
      label: labelsVisible ? e.relations.map(relName).join(' / ') + (e.cross ? '（跨工程）' : '') : '',
      relationText: e.relations.map(relName).join(' / ') + (e.cross ? '（跨工程）' : ''),
      evidence: e.evidence, evidenceTotal: e.evidenceTotal, style: e.cross ? {stroke:'#8b5cf6',lineWidth:2,lineDash:[6,3],endArrow:true} : {endArrow:true},
    })),
  });
  graph.render();
  for (const n of nodes) if (!positions.has(n.id) && layout[n.id]) positions.set(n.id, layout[n.id]!);
  container.dataset.renderer = 'canvas';
  container.dataset.ready = 'true';
  container.dataset.nodeCount = String(nodes.length); container.dataset.edgeCount = String(edges.length);
  container.dataset.relationLabels = JSON.stringify(edges.map(e => relName(e.rel)));
  const showNodeHint = (event: any) => {
    if (graph !== instance) return;
    const node = nodeIndex.get(event.item.getID());
    if (!node) return;
    const rect = container.getBoundingClientRect();
    container.style.cursor = 'pointer'; instance.setItemState(event.item, 'hover', true);
    hoverTip.value = { name: node.name, type: LABEL_NAMES[node.label] || node.label,
      x: Math.max(8, Math.min(rect.width - 250, event.clientX - rect.left + 16)),
      y: Math.max(8, Math.min(rect.height - 85, event.clientY - rect.top + 16)) };
  };
  instance.on('node:mouseenter', showNodeHint); instance.on('node:mousemove', showNodeHint);
  instance.on('node:mouseleave', (event: any) => { if (graph !== instance) return; instance.setItemState(event.item, 'hover', false); hoverTip.value = undefined; container.style.cursor = ''; });
  graph.on('node:click', (evt: any) => {
    hoverTip.value = undefined;
    const id = evt.item.getID();
    graph?.setItemState(evt.item, 'selected', true);
    openDetail(id);
  });
  graph.on('node:dragend', (event: any) => { const node = event.item.getModel(); positions.set(node.id, { x: node.x, y: node.y }); });
  graph.on('viewportchange', updateRelationLabels);
}

function openDetail(id: string) {
  const node = allNodes.value.find((n) => n.id === id);
  if (!node) return;
  detail.value = {
    node,
    inEdges: allEdges.value.filter((e) => e.dst === id),
    outEdges: allEdges.value.filter((e) => e.src === id),
  };
  detailOpen.value = true;
}

function relName(rel: string) {
  return REL_NAMES[rel] ?? rel;
}

function triples() {
  const { edges } = currentData();
  return edges.map((e) => ({
    dst: e.dst,
    key: `${e.src}-${e.rel}-${e.dst}-${(e as any).props?.line || 0}`,
    rel: relName(e.rel),
    src: e.src,
  }));
}

async function load() {
  const request = ++requestSequence;
  loading.value = true;
  try {
    positions.clear();
    const params = { library: library.value, project: projectFilter.value, version: versionFilter.value, tag: tagFilter.value, detail: detailFilter.value, doc_id: fileId.value, neighbors: neighbors.value, view: view.value, cross_system: crossSystem.value, limit: 1000 };
    const data = await graphStruct(params);
    if (request !== requestSequence) return;
    truncated.value = !!(data as any).truncated;
    allNodes.value = data.nodes;
    allEdges.value = data.edges;
    Object.assign(stats, data.stats);
    buildNameIndex();
    const labels = Object.keys(data.stats.by_label ?? {}).sort(
      (a, b) => (data.stats.by_label?.[b] ?? 0) - (data.stats.by_label?.[a] ?? 0),
    );
    labelOptions.value = labels.map((l) => ({
      label: `${LABEL_NAMES[l] ?? l} (${data.stats.by_label?.[l] ?? 0})`,
      value: l,
    }));
    selectedLabels.value = labels;
    await nextTick();
    await renderGraph();
    let offset = data.pagination?.next_offset;
    while (offset != null) {
      const page = await graphStruct({ ...params, offset });
      if (request !== requestSequence) return;
      if ((page as any).generation !== (data as any).generation) throw new Error('加载期间图谱已更新，请刷新以查看完整的新版本');
      allNodes.value = [...allNodes.value, ...page.nodes]; allEdges.value = [...allEdges.value, ...page.edges];
      offset = page.pagination?.next_offset;
      truncated.value = offset != null;
      await new Promise(resolve => window.setTimeout(resolve, 0));
    }
    if (data.pagination?.next_offset != null) { positions.clear(); buildNameIndex(); await nextTick(); await renderGraph(); }
  } catch (e: any) {
    message.error(e?.message ?? '图谱加载失败');
  } finally {
    if (request === requestSequence) loading.value = false;
  }
}

function onResize() {
  if (!graph || !containerRef.value) return;
  graph.changeSize(containerRef.value.clientWidth, Math.max(360, containerRef.value.clientHeight || 480));
}

async function refresh() {
  versionFilter.value = String(route.query.version || '');
  await scope.initialize(route.query, fileFilters());
  keyword.value = '';
  if (fileId.value) detailFilter.value = true;
  await Promise.all([loadVersions(), load()]);
  if (fileId.value) await scope.loadFiles(fileFilters());
}
function fileFilters() { return { version: versionFilter.value, history: !!versionFilter.value, status: 'published' }; }
async function loadVersions() { const rows = await getProjectVersions(library.value, projectFilter.value); if (file.value && fileId.value) versionFilter.value = rows.find(v => v.id === file.value?.project_job)?.version || file.value.version; versionOptions.value = [...new Set([...rows.map(v => v.version), ...(file.value && fileId.value ? [versionFilter.value] : [])])].map(version => ({ label: version, value: version })); }
async function filterChanged(system = false) { versionFilter.value = ''; keyword.value = ''; await scope.reset(system, fileFilters()); await loadVersions(); await load(); }
async function versionChanged() { keyword.value = ''; await scope.reset(false, fileFilters()); await load(); }
async function selectFile() { keyword.value = ''; if (fileId.value) { file.value = await getKmDoc(fileId.value); library.value = file.value.path; projectFilter.value = file.value.project || ''; detailFilter.value = true; } else file.value = undefined; await scope.refreshOptions(); await loadVersions(); await scope.loadFiles(fileFilters()); await load(); }
async function tagChanged() { await scope.reset(false, fileFilters()); await loadVersions(); await load(); }
const palette = ['#5B8FF9','#21A79B','#9B6FFF','#E89848','#E8687B','#55A7C7'];
function projectColor(value: string) { return projectColors.value.get(value) || palette[0]; }
function legendName(key: string) { const n = allNodes.value.find(n => n.props.library + '/' + (n.props.project || '系统通用') === key); return n ? (systems.value.find(s => s.value === n.props.library)?.label || n.props.library) + ' / ' + (n.props.project || '系统通用') : key; }
const projectLegend = computed(() => [...new Set(allNodes.value.map(n => n.props.library + '/' + (n.props.project || '系统通用')))]);
const projectColors = computed(() => { const result = new Map<string,string>(), used = new Set<number>(); for (const key of [...projectLegend.value].sort()) { let h=0; for (const c of key) h=(h*31+c.charCodeAt(0))>>>0; let index=h % palette.length; for (let n=0; n<palette.length && used.has(index); n++) index=(index+1)%palette.length; used.add(index); result.set(key,palette[index]!); } return result; });
async function centerFile(id: string) { fileId.value = id; detailOpen.value = false; relationOpen.value = false; await selectFile(); }
async function cleanup() { await confirmCleanup({ target: 'graph', ...(fileId.value ? { doc_id: fileId.value } : { library: library.value, project: projectFilter.value, version: versionFilter.value }) }, load); }
watch(activeTab, () => { void nextTick(renderGraph); });
onMounted(() => { window.addEventListener('resize', onResize); void refresh(); });
watch(() => route.fullPath, () => { if (route.path === '/kb/graph') void refresh(); });
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  const previous = graph; graph = undefined; previous?.destroy();
  requestSequence++;
  renderSequence++; layoutWorker?.terminate(); layoutTasks.clear();
});
</script>

<template>
  <Page>
    <div class="g-wrap">
      <Card style="margin-bottom:16px"><div class="scope-filters">
        <label>所属系统<ASelect :value="library || undefined" @update:value="library = String($event || '')" allow-clear show-search option-filter-prop="label" placeholder="全部系统" :options="systems" @change="filterChanged(true)" /></label>
        <label>工程<ASelect :value="projectFilter || undefined" @update:value="projectFilter = String($event || '')" allow-clear show-search option-filter-prop="label" placeholder="全部工程" :options="projects" @change="filterChanged()" /></label>
        <label>版本<ASelect :value="versionFilter || undefined" @update:value="versionFilter = String($event || '')" allow-clear placeholder="当前成功版本" :options="versionOptions" @change="versionChanged" /></label>
        <label class="file-filter">单独文件<ASelect :value="fileId || undefined" @update:value="fileId = String($event || '')" allow-clear show-search :filter-option="false" :options="files" :loading="scope.loading.value" placeholder="全部文件，可搜索并选择关联中心" @search="scope.searchFiles($event, fileFilters())" @popup-scroll="scope.loadMore($event, fileFilters())" @change="selectFile" /></label>
        <label>主题标签<ASelect :value="tagFilter || undefined" @update:value="tagFilter = String($event || '')" allow-clear placeholder="全部主题" :options="catalog.tags.map(t => ({ label:t.value, value:t.value }))" @change="tagChanged" /></label>
      </div><div class="scope-actions"><RadioGroup v-model:value="view" button-style="solid" @change="load"><RadioButton value="files">文件关联</RadioButton><RadioButton value="structure">结构细节</RadioButton></RadioGroup><ACheckbox v-if="view === 'structure'" v-model:checked="detailFilter" @change="load">展开段落和字段</ACheckbox><ACheckbox v-model:checked="neighbors" :disabled="!fileId && !projectFilter" @change="load">包含关联文件</ACheckbox><ACheckbox v-model:checked="crossSystem" @change="load">跨系统静态关联</ACheckbox><ACheckbox v-model:checked="showRelations" @change="updateRelationLabels">显示关系文字（大图放大后显示）</ACheckbox><AButton @click="load">刷新</AButton><AButton danger :disabled="!canClean" @click="cleanup">{{ fileId ? '清理文件图谱' : '清理工程图谱' }}</AButton></div>
      </Card>
      <AAlert v-if="truncated && !loading" type="warning" show-icon message="加载未完成，当前显示部分数据，请刷新重试。" style="margin-bottom:16px" />
      <Card :body-style="{ padding: '14px 20px' }">
        <div class="g-head">
          <div>
            <div class="g-title">知识图谱总览</div>
            <div class="g-sub">
              当前筛选范围：{{ stats.nodes }} 个{{ view === 'files' ? '文件节点' : '节点' }} ·
              {{ stats.edges }} 条关系 ·
              {{ stats.cross_project }} 条跨工程关系；拖拽/滚轮缩放，点击节点或关系查看依据
            </div>
          </div>
          <div class="g-tools">
            <span v-if="view === 'structure'" class="entity-label">实体类型</span><ASelect v-if="view === 'structure'"
              v-model:value="selectedLabels"
              :max-tag-count="3"
              :options="labelOptions"
              mode="multiple"
              placeholder="按实体类型筛选"
              style="min-width: 300px"
              @change="renderGraph"
            />
            <AInput
              v-model:value="keyword"
              allow-clear
              placeholder="搜索实体（如 ATMWD402 / 错误码14 / Smart卡）"
              style="width: 260px"
              @press-enter="renderGraph"
              @change="() => !keyword && renderGraph()"
            />
            <AButton @click="graph?.fitView(40)">适应全图</AButton>
          </div>
        </div>
        <p class="file-caption" role="status">{{ loadedText }}</p><details class="type-help"><summary>实体类型如何区分？</summary><p>代码文件对应物理文件；程序对应 PROGRAM-ID；段落 / SECTION 和字段是文件内的结构。Copybook 引用按解析出的引用节点计数，同一个 Copybook 可以出现多次，因此不等于实际 Copybook 文件数。主题标签是上传时填写的业务分类。</p></details>
        <p v-if="fileId" class="file-caption">当前文件：{{ file?.name }}。虚线边框节点来自关联文件，可点击节点继续查看。</p>
      </Card>

      <p class="file-caption">紫色虚线表示跨工程静态匹配。仅使用字面量 CALL、COPY 和唯一同名定义；同名冲突或动态调用不会自动连线。新上传成功后自动使用当前有效版本重新匹配。</p><div v-if="view === 'files'" class="g-legend"><span v-for="key in projectLegend" :key="key" class="lg-item"><i class="lg-dot" :style="{background:projectColor(key)}"></i>{{ legendName(key) }}</span></div><Card class="mt" :body-style="{ padding: '12px' }">
        <ATabs v-model:active-key="activeTab">
          <ATabPane key="graph" tab="图谱视图">
            <ASpin :spinning="loading && !allNodes.length">
              <div class="graph-frame"><div ref="containerRef" class="g-canvas"></div><div v-if="hoverTip" role="tooltip" class="node-hint" :style="{left:hoverTip.x+'px',top:hoverTip.y+'px'}"><strong>{{ hoverTip.name }}</strong><span>{{ hoverTip.type }} · 点击查看详细信息</span></div><AEmpty v-if="!loading && !allNodes.length" class="graph-empty" description="当前范围没有图谱数据，可切换文件或重新上传解析" /></div>
              <div class="g-legend">
                <span
                  v-for="(color, label) in LABEL_COLORS"
                  :key="label"
                  v-show="(stats.by_label ?? {})[label]"
                  class="lg-item"
                >
                  <span class="lg-dot" :style="{ background: color }"></span>
                  {{ LABEL_NAMES[label] ?? label }}
                </span>
              </div>
            </ASpin>
          </ATabPane>
          <ATabPane key="triples" tab="三元组列表">
            <ATable
              :columns="tripleColumns"
              :data-source="triples()"
              :pagination="{ pageSize: 15 }"
              row-key="key"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'src' || column.key === 'dst'">
                  <span class="tri-node" @click="openDetail(record[column.key])">
                    <span
                      class="lg-dot"
                      :style="{
                        background:
                          LABEL_COLORS[nameOf[record[column.key]]?.label || ''] ?? '#999',
                      }"
                    ></span>
                    {{ nameOf[record[column.key]]?.name ?? record[column.key] }}
                  </span>
                </template>
                <template v-else-if="column.key === 'rel'">
                  <ATag color="blue">{{ record.rel }}</ATag>
                </template>
              </template>
              <template #emptyText>
                <AEmpty description="无匹配的三元组" />
              </template>
            </ATable>
          </ATabPane>
        </ATabs>
      </Card>

      <ADrawer v-model:open="relationOpen" title="文件关系与依据" width="560"><template v-if="relationDetail"><p>共 {{ relationDetail.evidenceTotal }} 处引用，显示前 20 处。</p><Card v-for="(e,i) in relationDetail.evidence.slice(0,20)" :key="i" size="small" class="mt"><ATag>{{ relName(e.rel) }}</ATag><ATag v-if="e.cross_project" color="purple">跨工程静态匹配</ATag><p>{{ e.source?.props.project }} / {{ e.source?.props.path || e.source?.name }} → {{ e.target?.props.project }} / {{ e.target?.props.path || e.target?.name }}</p><p>{{ e.reason || 'CodeGraph 解析关系' }}{{ e.line ? ' · 第 ' + e.line + ' 行' : '' }}</p><pre v-if="e.evidence" style="white-space:pre-wrap">{{ e.evidence }}</pre><AButton v-if="e.source?.props.doc_id" type="link" @click="router.push({path:'/knowledge/chunk',query:{doc:e.source.props.doc_id}})">查看来源文件</AButton><AButton v-if="e.target?.props.doc_id" type="link" @click="centerFile(e.target.props.doc_id)">查看目标关联</AButton></Card></template></ADrawer>
      <ADrawer v-model:open="detailOpen" :title="detail?.node?.name" width="480">
        <template v-if="detail">
          <ATag :color="LABEL_COLORS[detail.node.label] ?? 'default'">
            {{ LABEL_NAMES[detail.node.label] ?? detail.node.label }}
          </ATag>
          <div v-if="detail.node.props.doc_id" class="mt"><AButton @click="centerFile(detail.node.props.doc_id)">以此文件为中心</AButton></div>
          <div v-if="detail.node.props.source_path || detail.node.props.doc_id" class="mt"><AButton v-if="detail.node.props.doc_id" type="link" @click="router.push({ path: '/knowledge/chunk', query: { doc: detail.node.props.doc_id } })">查看原文与切片</AButton></div>
          <ADescriptions class="mt" :column="1" bordered size="small" title="节点属性">
            <ADescriptionsItem label="ID">
              <span class="mono">{{ detail.node.id }}</span>
            </ADescriptionsItem>
            <ADescriptionsItem
              v-for="(v, k) in detail.node.props"
              :key="k"
              :label="k"
            >
              {{ v }}
            </ADescriptionsItem>
          </ADescriptions>
          <ARow :gutter="12" class="mt">
            <ACol :span="12">
              <Card size="small" title="出边（它指向）">
                <div
                  v-for="(e, i) in detail.outEdges"
                  :key="i"
                  class="rel-row"
                  @click="openDetail(e.dst)"
                >
                  <ATag size="small">{{ relName(e.rel) }}</ATag>
                  {{ nameOf[e.dst]?.name ?? e.dst }}
                </div>
                <div v-if="!detail.outEdges.length" class="empty-tip">无</div>
              </Card>
            </ACol>
            <ACol :span="12">
              <Card size="small" title="入边（被指向）">
                <div
                  v-for="(e, i) in detail.inEdges"
                  :key="i"
                  class="rel-row"
                  @click="openDetail(e.src)"
                >
                  <ATag size="small">{{ relName(e.rel) }}</ATag>
                  {{ nameOf[e.src]?.name ?? e.src }}
                </div>
                <div v-if="!detail.inEdges.length" class="empty-tip">无</div>
              </Card>
            </ACol>
          </ARow>
        </template>
      </ADrawer>
    </div>
  </Page>
</template>

<style lang="scss" scoped>
.scope-filters{display:flex;gap:12px;flex-wrap:wrap}.scope-filters label{display:flex;flex-direction:column;gap:8px;flex:1;min-width:150px;font-size:13px}.scope-filters .file-filter{flex:2;min-width:260px}.scope-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:18px}.file-pages{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:14px;color:hsl(var(--muted-foreground));font-size:12px}.type-help,.file-caption{font-size:12px;color:hsl(var(--muted-foreground));margin-top:12px}.type-help summary{cursor:pointer}.type-help p{line-height:1.8;margin-top:8px}.entity-label{font-size:13px;color:hsl(var(--muted-foreground))}
.mt {
  margin-top: 12px;
}

.mono {
  font-family: monospace;
  font-size: 12px;
}

.g-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.g-title {
  font-size: 16px;
  font-weight: 600;
}

.g-sub {
  margin-top: 2px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.g-tools {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.g-canvas {
  position: relative;
  width: 100%;
  height: 480px;
  background:
    radial-gradient(circle, hsl(var(--border)) 1px, transparent 1px) 0 0 / 20px 20px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
}
.graph-frame{position:relative}.graph-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none}
.node-hint{position:absolute;z-index:3;display:flex;flex-direction:column;gap:5px;max-width:240px;padding:10px 13px;background:hsl(var(--popover));color:hsl(var(--popover-foreground));border:1px solid hsl(var(--primary));border-radius:8px;box-shadow:0 4px 16px #0002;pointer-events:none;font-size:12px;overflow-wrap:anywhere}.node-hint span{color:hsl(var(--muted-foreground))}

.g-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 4px 2px;

  .lg-item {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    font-size: 12px;
    color: hsl(var(--muted-foreground));
  }

  .lg-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }
}

.tri-node {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  cursor: pointer;

  .lg-dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
  }

  &:hover {
    color: hsl(var(--primary));
  }
}

.rel-row {
  padding: 3px 0;
  font-size: 13px;
  cursor: pointer;

  &:hover {
    color: hsl(var(--primary));
  }
}

.empty-tip {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
</style>
