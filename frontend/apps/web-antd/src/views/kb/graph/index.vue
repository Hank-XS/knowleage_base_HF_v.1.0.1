<script lang="ts" setup>
import type { GraphEdge, GraphNode } from '#/api/kb';

import { onActivated, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import G6 from '@antv/g6';
import {
  Button as AButton,
  Card as ACard,
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
  System: '#5B8FF9',
  SubSystem: '#5AD8A6',
  FunctionPoint: '#F6BD16',
  BusinessProcess: '#E8684A',
  BusinessRule: '#6DC8EC',
  ErrorCode: '#FF9D4D',
  CardType: '#9270CA',
  Interface: '#269A99',
  CodeUnit: '#5D7092',
  CopyBook: '#9FB1FC',
  TechComponent: '#BFBFBF',
  DataTable: '#FF85C0',
  MessageFormat: '#A0D911',
  Field: '#C2C8D0',
  Tag: '#FAAD14',
};
const LABEL_NAMES: Record<string, string> = {
  System: '系统',
  SubSystem: '子系统',
  FunctionPoint: '功能点',
  BusinessProcess: '业务流程',
  BusinessRule: '业务规则',
  ErrorCode: '错误码',
  CardType: '卡种',
  Interface: '接口',
  CodeUnit: '代码单元',
  CopyBook: '拷贝书',
  TechComponent: '技术组件',
  DataTable: '数据表',
  MessageFormat: '报文格式',
  Field: '字段',
  Tag: '标签',
};
const REL_NAMES: Record<string, string> = {
  PART_OF: '属于',
  REALIZED_BY: '实现于',
  CALLS: '调用',
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

const loading = ref(true);
const allNodes = ref<GraphNode[]>([]);
const allEdges = ref<GraphEdge[]>([]);
const stats = reactive({ edges: 0, nodes: 0, by_label: {} as Record<string, number> });

const labelOptions = ref<{ label: string; value: string }[]>([]);
const selectedLabels = ref<string[]>([]);
const keyword = ref('');

const activeTab = ref('graph');
const detailOpen = ref(false);
const detail = ref<{ node: GraphNode; inEdges: GraphEdge[]; outEdges: GraphEdge[] } | null>(null);
const nameOf = ref<Record<string, { label: string; name: string }>>({});

const containerRef = ref<HTMLElement>();
let graph: any = null;

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

function renderGraph() {
  const container = containerRef.value;
  if (!container || activeTab.value !== 'graph') return;
  const { nodes, edges } = currentData();
  graph?.destroy();
  graph = new G6.Graph({
    container,
    height: Math.max(520, container.clientHeight || 620),
    width: container.clientWidth || 900,
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    layout: {
      type: 'force',
      preventOverlap: true,
      nodeStrength: -70,
      linkDistance: 95,
      nodeSpacing: 36,
      collide: 22,
      alphaDecay: 0.028,
    },
    defaultNode: {
      type: 'circle',
      size: 26,
      labelCfg: { position: 'bottom', style: { fontSize: 10, fill: '#888' } },
    },
    defaultEdge: {
      style: { endArrow: true, stroke: '#c5cdd8', lineWidth: 1 },
    },
    nodeStateStyles: {
      selected: { stroke: '#f5222d', lineWidth: 2.5 },
    },
  });
  graph.data({
    nodes: nodes.map((n) => ({
      id: n.id,
      label: n.name.length > 14 ? `${n.name.slice(0, 13)}…` : n.name,
      size: ['FunctionPoint', 'Interface'].includes(n.label) ? 36 : 26,
      style: { fill: LABEL_COLORS[n.label] ?? '#9099A6' },
    })),
    edges: edges.map((e, i) => ({
      id: `e${i}-${e.src}-${e.rel}-${e.dst}`,
      source: e.src,
      target: e.dst,
    })),
  });
  graph.render();
  graph.on('node:click', (evt: any) => {
    const id = evt.item.getID();
    graph?.setItemState(evt.item, 'selected', true);
    openDetail(id);
  });
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
    key: `${e.src}-${e.rel}-${e.dst}`,
    rel: relName(e.rel),
    src: e.src,
  }));
}

async function load() {
  loading.value = true;
  try {
    const data = await graphStruct();
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
    renderGraph();
  } catch (e: any) {
    message.error(e?.message ?? '图谱加载失败');
  } finally {
    loading.value = false;
  }
}

function onResize() {
  if (!graph || !containerRef.value) return;
  graph.changeSize(containerRef.value.clientWidth, Math.max(520, containerRef.value.clientHeight || 620));
}

onMounted(async () => {
  await load();
  window.addEventListener('resize', onResize);
});
// 从治理工作台切回来时重新拉图谱，避免仍显示旧快照
onActivated(() => {
  void load();
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  graph?.destroy();
});
</script>

<template>
  <Page>
    <div class="g-wrap">
      <Card :body-style="{ padding: '14px 20px' }">
        <div class="g-head">
          <div>
            <div class="g-title">知识图谱总览</div>
            <div class="g-sub">
              业务层 / 数据层 / 执行层三层建模：{{ stats.nodes }} 个节点 ·
              {{ stats.edges }} 条关系 ·
              {{ Object.keys(stats.by_label ?? {}).length }} 类实体；拖拽/滚轮缩放，点击节点查看详情
            </div>
          </div>
          <div class="g-tools">
            <ASelect
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
            <AButton @click="renderGraph">重绘</AButton>
          </div>
        </div>
      </Card>

      <Card class="mt" :body-style="{ padding: '12px' }">
        <ATabs v-model:active-key="activeTab">
          <ATabPane key="graph" tab="图谱视图">
            <ASpin :spinning="loading">
              <div ref="containerRef" class="g-canvas"></div>
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
                          LABEL_COLORS[nameOf[record[column.key]]?.label] ?? '#999',
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

      <ADrawer v-model:open="detailOpen" :title="detail?.node?.name" width="480">
        <template v-if="detail">
          <ATag :color="LABEL_COLORS[detail.node.label] ?? 'default'">
            {{ LABEL_NAMES[detail.node.label] ?? detail.node.label }}
          </ATag>
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
  height: 620px;
  background:
    radial-gradient(circle, #f0f0f0 1px, transparent 1px) 0 0 / 20px 20px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
}

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
