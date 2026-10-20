<script lang="ts" setup>
import type { TaggingTask } from '#/api/kb';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  Input as AInput,
  RadioButton as ARadioButton,
  RadioGroup as ARadioGroup,
  Select as ASelect,
  Space as ASpace,
  Spin as ASpin,
  Table as ATable,
  Tag as ATag,
  Tooltip as ATooltip,
  message,
} from 'ant-design-vue';

import {
  addVocab,
  batchTagReview,
  listTaggingTasks,
  listVocab,
  reviewVocab,
  submitTagReview,
  triggerCrossTag,
} from '#/api/kb';

defineOptions({ name: 'KbGovernance' });

const loading = ref(false);
const statusFilter = ref<'all' | 'done' | 'pending'>('pending');
const tasks = ref<TaggingTask[]>([]);
const listTotal = ref(0);
const pendingTotal = ref(0);
const current = ref<TaggingTask | null>(null);
const decisions = ref<Record<string, 'accept' | 'reject'>>({});
const submitting = ref(false);
const batchLoading = ref(false);
const xtagLoading = ref(false);
const selectedRowKeys = ref<string[]>([]);

const selectedPendingTasks = computed(() =>
  tasks.value.filter(
    (t) => selectedRowKeys.value.includes(t.id) && t.status !== 'done',
  ),
);

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys: (string | number)[]) => {
    selectedRowKeys.value = keys.map(String);
  },
  getCheckboxProps: (record: TaggingTask) => ({
    disabled: record.status === 'done',
  }),
}));

// ---- 标签词表 ----
const vocabRows = ref<any[]>([]);
const vocabLoading = ref(false);
const newVocabCategory = ref('功能域');
const newVocabValue = ref('');
const VOCAB_CATEGORIES = ['功能域', '业务对象', '治理', '技术属性'];

const columns = [
  { title: '任务', dataIndex: 'title', key: 'title' },
  { title: '类型', dataIndex: 'task_type', key: 'task_type', width: 110 },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    width: 90,
  },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 90 },
];

const vocabColumns = [
  { title: '分类', dataIndex: 'category', key: 'category', width: 110 },
  { title: '标签', dataIndex: 'value', key: 'value', width: 160 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
  { title: '来源', dataIndex: 'created_by', key: 'created_by', width: 100 },
  { title: '操作', key: 'action', width: 140 },
];

async function load() {
  loading.value = true;
  try {
    const status = statusFilter.value === 'all' ? undefined : statusFilter.value;
    const res = await listTaggingTasks(status);
    tasks.value = res.items ?? [];
    listTotal.value = res.total ?? tasks.value.length;
    pendingTotal.value = res.pending_total ?? 0;
    // 筛选变更后，若当前任务不在列表中则清空明细，避免展示错位
    if (
      current.value &&
      !tasks.value.some((t) => t.id === current.value!.id)
    ) {
      current.value = null;
      decisions.value = {};
    }
    const alive = new Set(
      tasks.value.filter((t) => t.status !== 'done').map((t) => t.id),
    );
    selectedRowKeys.value = selectedRowKeys.value.filter((id) => alive.has(id));
  } catch (e: any) {
    message.error(e?.message ?? '加载失败');
  } finally {
    loading.value = false;
  }
}

watch(statusFilter, () => {
  selectedRowKeys.value = [];
  void load();
});

async function loadVocab() {
  vocabLoading.value = true;
  try {
    vocabRows.value = await listVocab();
  } catch {
    vocabRows.value = [];
  } finally {
    vocabLoading.value = false;
  }
}

async function doCrossTag() {
  xtagLoading.value = true;
  try {
    const r = await triggerCrossTag(8);
    if (r.skipped) {
      message.warning(`交叉打标跳过：${r.reason}`);
    } else {
      message.success(
        `交叉打标完成：${r.units} 个程序｜自动通过 ${r.auto_applied} 条（已入图谱），待校对 ${r.pending_items} 条`,
      );
      await load();
    }
  } catch (e: any) {
    message.error(e?.message ?? '交叉打标失败');
  } finally {
    xtagLoading.value = false;
  }
}

async function doAddVocab() {
  if (!newVocabValue.value.trim()) return;
  try {
    await addVocab(newVocabCategory.value, newVocabValue.value.trim());
    message.success('已加入词表');
    newVocabValue.value = '';
    await loadVocab();
  } catch (e: any) {
    message.error(e?.message ?? '新增失败');
  }
}

async function doReviewVocab(id: number, action: 'approve' | 'reject') {
  try {
    await reviewVocab(id, action);
    await loadVocab();
  } catch (e: any) {
    message.error(e?.message ?? '操作失败');
  }
}

function confColor(c?: number) {
  if (!c) return 'default';
  return c >= 0.9 ? 'green' : c >= 0.6 ? 'orange' : 'red';
}

function evDocTip(it: any, ev: string): string {
  const docs = (it.doc_evidence || []) as Array<{ excerpt: string; path: string }>;
  if (ev.startsWith('doc:')) {
    const d = docs[Number(ev.slice(4)) - 1];
    if (d) return `${d.path}\n${d.excerpt}`;
  }
  if (ev.startsWith('code:')) {
    return `代码证据：${ev.slice(5)}`;
  }
  return ev;
}

onMounted(() => {
  load();
  loadVocab();
});

function openTask(task: TaggingTask) {
  current.value = task;
  // 点选任务后默认全部通过，可再改单项或点「全部驳回」
  setAllDecisions('accept');
}

function setAllDecisions(action: 'accept' | 'reject') {
  const next: Record<string, 'accept' | 'reject'> = {};
  for (const it of current.value?.items ?? []) {
    if (it?.item_id) next[it.item_id] = action;
  }
  decisions.value = next;
}

/** 明细区「全部通过/驳回」：直接提交当前任务（不再只改本地单选） */
async function submitCurrentAll(action: 'accept' | 'reject') {
  if (!current.value) {
    message.warning('请先点选左侧任务');
    return;
  }
  setAllDecisions(action);
  await submit();
}

async function batchReview(action: 'accept' | 'reject') {
  const selected = selectedPendingTasks.value;
  if (!selected.length) {
    message.warning('请先勾选待校对任务');
    return;
  }
  // 表头全选 + 当前是「待校对」：一次清空全部待校对（避免只处理当前页后列表又被下一批填满）
  const selectAllVisible =
    selectedRowKeys.value.length === tasks.value.length &&
    tasks.value.length > 0;
  const clearAllPending =
    statusFilter.value === 'pending' &&
    selectAllVisible &&
    pendingTotal.value > 0;

  batchLoading.value = true;
  try {
    const res = await batchTagReview({
      action,
      all_pending: clearAllPending,
      task_ids: clearAllPending ? [] : selected.map((t) => t.id),
    });
    const remain = res.remaining_pending ?? 0;
    message.success(
      clearAllPending
        ? `已${action === 'accept' ? '通过' : '驳回'}全部待校对：处理 ${res.processed} 个任务（条目 ${res.applied + res.rejected}），剩余 ${remain}`
        : `已处理 ${res.processed} 个任务：通过 ${res.applied} 条，驳回 ${res.rejected} 条；仍有 ${remain} 个待校对`,
    );
    if (res.errors?.length) {
      message.warning(`${res.errors.length} 个任务处理失败，请重试或逐条校对`);
    }
    selectedRowKeys.value = [];
    current.value = null;
    decisions.value = {};
    await load();
  } catch (e: any) {
    message.error(e?.message ?? '批量操作失败');
  } finally {
    batchLoading.value = false;
  }
}

async function submit() {
  if (!current.value) return;
  submitting.value = true;
  try {
    const items = (current.value.items ?? [])
      .filter((it) => decisions.value[it.item_id])
      .map((it) => ({
        action: decisions.value[it.item_id],
        item_id: it.item_id,
        reason:
          decisions.value[it.item_id] === 'reject' ? '治理工作台人工驳回' : '',
      }));
    const taskId = current.value.id;
    const res = await submitTagReview(taskId, items);
    message.success(
      `校对完成：通过 ${res.applied ?? 0} 条，驳回 ${res.rejected ?? 0} 条（标签已写入知识图谱）`,
    );
    current.value = null;
    selectedRowKeys.value = selectedRowKeys.value.filter((id) => id !== taskId);
    await load();
  } catch (e: any) {
    message.error(e?.message ?? '提交失败');
  } finally {
    submitting.value = false;
  }
}

function statusColor(s: string) {
  return s === 'done' ? 'green' : 'orange';
}

function fmtTime(t: string) {
  return t?.replace('T', ' ').slice(0, 19);
}
</script>

<template>
  <Page>
    <div class="gov-wrap">
      <ACard :body-style="{ padding: '14px 20px' }">
        <div class="gov-head">
          <div>
            <div class="gov-title">治理工作台 · AI 解析结果人工校对</div>
            <div class="gov-sub">
              数据治理三步法：梳理功能点 → AI 打标签 → 人工校对（本页）→
              标签入知识图谱；AI 交叉打标 = 受控词表 × 代码结构 × 文档证据，置信度
              ≥0.9 自动通过、0.4~0.9 待人工校对
            </div>
          </div>
          <ASpace>
            <AButton :loading="xtagLoading" type="primary" ghost @click="doCrossTag">
              执行 AI 交叉打标
            </AButton>
            <ARadioGroup v-model:value="statusFilter" button-style="solid">
              <ARadioButton value="pending">待校对</ARadioButton>
              <ARadioButton value="done">已完成</ARadioButton>
              <ARadioButton value="all">全部</ARadioButton>
            </ARadioGroup>
          </ASpace>
        </div>
      </ACard>

      <div class="gov-main">
        <ACard class="gov-list" :body-style="{ padding: '12px' }">
          <div class="gov-list-toolbar">
            <span class="gov-list-hint">
              待校对 {{ pendingTotal }} 条 · 当前列表 {{ tasks.length }}/{{
                listTotal
              }}
              {{
                selectedRowKeys.length
                  ? ` · 已勾选 ${selectedRowKeys.length}`
                  : ' · 表头全选后点全部通过将清空全部待校对'
              }}
            </span>
            <ASpace>
              <AButton
                :disabled="!selectedPendingTasks.length"
                :loading="batchLoading"
                type="primary"
                @click="batchReview('accept')"
              >
                全部通过
              </AButton>
              <AButton
                :disabled="!selectedPendingTasks.length"
                :loading="batchLoading"
                danger
                @click="batchReview('reject')"
              >
                全部驳回
              </AButton>
            </ASpace>
          </div>
          <ASpin :spinning="loading">
            <ATable
              :columns="columns"
              :custom-row="
                (record: TaggingTask) => ({
                  onClick: () => openTask(record),
                  style: {
                    cursor: 'pointer',
                    background:
                      current?.id === record.id
                        ? 'hsl(var(--accent) / 0.35)'
                        : undefined,
                  },
                })
              "
              :data-source="tasks"
              :pagination="false"
              :row-selection="rowSelection"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'status'">
                  <ATag
                    :color="statusColor(record.status)"
                    style="cursor: pointer"
                    @click.stop="openTask(record)"
                  >
                    {{ record.status === 'done' ? '已完成' : '待校对' }}
                  </ATag>
                </template>
                <template v-else-if="column.key === 'created_at'">
                  {{ fmtTime(record.created_at) }}
                </template>
                <template v-else-if="column.key === 'action'">
                  <AButton
                    size="small"
                    type="link"
                    @click.stop="openTask(record)"
                  >
                    校对
                  </AButton>
                </template>
              </template>
              <template #emptyText>
                <AEmpty description="暂无任务（接入新素材后自动生成打标任务）" />
              </template>
            </ATable>
          </ASpin>
        </ACard>

        <ACard
          class="gov-detail"
          :body-style="{ padding: '16px' }"
          :title="current ? current.title : '校对明细'"
        >
          <template v-if="current">
            <div class="gov-toolbar">
              <ASpace>
                <AButton
                  :loading="submitting"
                  size="small"
                  type="primary"
                  @click="submitCurrentAll('accept')"
                >
                  全部通过
                </AButton>
                <AButton
                  :loading="submitting"
                  danger
                  size="small"
                  @click="submitCurrentAll('reject')"
                >
                  全部驳回
                </AButton>
              </ASpace>
              <AButton
                :loading="submitting"
                type="primary"
                ghost
                @click="submit"
              >
                提交校对结果
              </AButton>
            </div>
            <div class="gov-items">
              <div
                v-for="it in current.items"
                :key="it.item_id"
                class="gov-item xtag-item"
              >
                <div class="gi-row">
                  <div class="gi-left">
                    <ATag :color="it.source === 'ai' ? 'purple' : 'blue'">
                      {{ it.source === 'ai' ? 'AI 标签' : '规则标签' }}
                    </ATag>
                    <ATag v-if="it.confidence" :color="confColor(it.confidence)">
                      置信 {{ it.confidence }}
                    </ATag>
                    <span class="gi-node">{{ it.node_name || it.node_id }}</span>
                  </div>
                  <div class="gi-mid">
                    <ATag color="cyan">{{ it.tag.category }}</ATag>
                    <span class="gi-value">{{ it.tag.value }}</span>
                  </div>
                  <ARadioGroup
                    v-model:value="decisions[it.item_id]"
                    size="small"
                  >
                    <ARadioButton value="accept">通过</ARadioButton>
                    <ARadioButton value="reject">驳回</ARadioButton>
                  </ARadioGroup>
                </div>
                <div v-if="it.reason || (it.evidence && it.evidence.length)" class="gi-evidence">
                  <div v-if="it.reason" class="gi-reason">
                    理由：{{ it.reason }}
                  </div>
                  <div v-if="it.evidence && it.evidence.length" class="gi-ev-list">
                    <ATooltip
                      v-for="(ev, i) in it.evidence"
                      :key="i"
                      :title="evDocTip(it, ev)"
                    >
                      <ATag class="gi-ev" color="geekblue">证据 {{ ev }}</ATag>
                    </ATooltip>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <AEmpty
            v-else
            class="gov-empty"
            description="从左侧选择任务开始校对"
          />
        </ACard>
      </div>

      <!-- 标签词表管理 -->
      <ACard :body-style="{ padding: '12px' }" title="标签词表（受控封闭集，LLM 只能从中选标签）">
        <div class="vocab-add">
          <ASelect
            v-model:value="newVocabCategory"
            :options="VOCAB_CATEGORIES.map((c) => ({ label: c, value: c }))"
            style="width: 130px"
          />
          <AInput
            v-model:value="newVocabValue"
            placeholder="新标签值（治理员/admin 添加后直接生效，其他角色进入候选）"
            style="width: 380px"
            @press-enter="doAddVocab"
          />
          <AButton type="primary" @click="doAddVocab">新增</AButton>
        </div>
        <ASpin :spinning="vocabLoading">
          <ATable
            :columns="vocabColumns"
            :data-source="vocabRows"
            :pagination="{ pageSize: 8 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <ATag :color="record.status === 'approved' ? 'green' : record.status === 'candidate' ? 'orange' : 'default'">
                  {{ record.status }}
                </ATag>
              </template>
              <template v-else-if="column.key === 'action'">
                <template v-if="record.status === 'candidate'">
                  <AButton size="small" type="link" @click="doReviewVocab(record.id, 'approve')">
                    批准
                  </AButton>
                  <AButton size="small" danger type="link" @click="doReviewVocab(record.id, 'reject')">
                    驳回
                  </AButton>
                </template>
                <span v-else>-</span>
              </template>
            </template>
          </ATable>
        </ASpin>
      </ACard>
    </div>
  </Page>
</template>

<style lang="scss" scoped>
.gov-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gov-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.gov-title {
  font-size: 16px;
  font-weight: 600;
}

.gov-sub {
  margin-top: 2px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.gov-main {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.gov-list {
  flex: 1;
  min-width: 0;
}

.gov-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 12px;
}

.gov-list-hint {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.gov-detail {
  width: 460px;
  flex-shrink: 0;
}

.gov-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid hsl(var(--border));
}

.gov-items {
  max-height: 560px;
  overflow-y: auto;
}

.gov-item {
  padding: 8px;
  margin-bottom: 6px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;

  .gi-row {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
  }

  .gi-left {
    display: flex;
    gap: 4px;
    align-items: center;
    min-width: 0;
  }

  .gi-evidence {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px dashed hsl(var(--border));

    .gi-reason {
      font-size: 12px;
      color: hsl(var(--muted-foreground));
      margin-bottom: 4px;
    }

    .gi-ev-list {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
  }

  .gi-node {
    max-width: 150px;
    overflow: hidden;
    font-family: monospace;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .gi-mid {
    display: flex;
    gap: 4px;
    align-items: center;
    flex: 1;
  }

  .gi-value {
    font-size: 13px;
  }
}

.gov-empty {
  margin-top: 120px;
}

.vocab-add {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}
</style>
