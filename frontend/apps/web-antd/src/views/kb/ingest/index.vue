<script lang="ts" setup>
import type { IngestJob } from '#/api/kb';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Card as ACard,
  Checkbox as ACheckbox,
  Empty as AEmpty,
  Select as ASelect,
  Steps as ASteps,
  Step as AStep,
  Table as ATable,
  Tag as ATag,
  Upload as AUpload,
  message,
} from 'ant-design-vue';

import {
  createIngestJob,
  getCleanManifest,
  importCleaned,
  listCleanConflicts,
  listCleanQuarantine,
  listIngestJobs,
  runDatasetClean,
} from '#/api/kb';
import ProjectTasks from './project-tasks.vue';

defineOptions({ name: 'KbIngest' });

const SOURCE_TYPES = [
  { label: '错误码表（csv/xlsx）', value: 'error_code_table' },
  { label: '字段映射 mapping（csv/xlsx）', value: 'mapping' },
  { label: '返回报文定义（json）', value: 'message_format' },
  { label: '业务文档（md/txt）', value: 'doc' },
  { label: 'COBOL 源码（cbl/txt）', value: 'cobol' },
];

const sourceType = ref('error_code_table');
const fileList = ref<any[]>([]);
const uploading = ref(false);
const jobs = ref<IngestJob[]>([]);
const lastJob = ref<IngestJob | null>(null);

const cleaning = ref(false);
const importing = ref(false);
const doImport = ref(true); // 默认清洗后接入图谱/向量
const includeTierC = ref(true); // CPS 合成语料（架构/SRS/PY*）在 tier C，默认一并接入
const manifest = ref<any>(null);
const quarantine = ref<any[]>([]);
const conflicts = ref<any[]>([]);
const lastImport = ref<null | { chunks: number; edges: number; nodes: number }>(
  null,
);

const columns = [
  { title: '任务', dataIndex: 'job_id', key: 'job_id', width: 130 },
  { title: '素材类型', dataIndex: 'source_type', key: 'source_type', width: 130 },
  { title: '素材', dataIndex: 'object_keys', key: 'object_keys' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
];

const quarColumns = [
  { title: '规则', dataIndex: 'rule', key: 'rule', width: 80 },
  { title: '路径', dataIndex: 'path', key: 'path' },
  { title: '原因', dataIndex: 'reason', key: 'reason', width: 220 },
  { title: '角色', dataIndex: 'role', key: 'role', width: 100 },
];

const conflictColumns = [
  { title: '规则', dataIndex: 'rule', key: 'rule', width: 80 },
  { title: '主题', dataIndex: 'subject', key: 'subject' },
  { title: '建议', dataIndex: 'suggestion', key: 'suggestion' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
];

async function load() {
  try {
    jobs.value = await listIngestJobs();
  } catch {
    jobs.value = [];
  }
}

async function loadClean() {
  try {
    manifest.value = await getCleanManifest();
  } catch {
    manifest.value = { exists: false };
  }
  try {
    const q = await listCleanQuarantine(30);
    quarantine.value = q.items ?? [];
  } catch {
    quarantine.value = [];
  }
  try {
    const c = await listCleanConflicts(30);
    conflicts.value = c.items ?? [];
  } catch {
    conflicts.value = [];
  }
}

onMounted(async () => {
  await load();
  await loadClean();
});

async function doUpload() {
  const file = fileList.value?.[0]?.originFileObj ?? fileList.value?.[0];
  if (!file) {
    message.warning('请先选择文件');
    return;
  }
  uploading.value = true;
  try {
    const job = await createIngestJob(file, sourceType.value);
    lastJob.value = job;
    message.success(
      job.status === 'done'
        ? '接入完成：parse → clean → tag → review → merge → index'
        : `接入${job.status === 'failed' ? '失败' : '处理中'}：${job.error || ''}`,
    );
    fileList.value = [];
    await load();
  } catch (e: any) {
    message.error(e?.message ?? '上传失败');
  } finally {
    uploading.value = false;
  }
}

async function doClean() {
  cleaning.value = true;
  lastImport.value = null;
  try {
    const res = await runDatasetClean(doImport.value, includeTierC.value);
    // 拉取任务详情以展示六步状态
    const jobsList = await listIngestJobs();
    const found = jobsList.find((j) => j.job_id === res.job_id);
    lastJob.value = found ?? {
      job_id: res.job_id,
      source_type: 'dataset_clean',
      object_keys: ['hf_data'],
      status: 'done',
      error: '',
      steps: [],
      created_at: new Date().toISOString(),
    };
    if (res.imported) {
      lastImport.value = res.imported;
    }
    const importMsg = res.imported
      ? `；已接入图谱 nodes=${res.imported.nodes} edges=${res.imported.edges}，向量 chunks=${res.imported.chunks}`
      : '';
    message.success(
      `hf_data 清洗完成：三元组 ${res.clean.kg_triples} / chunk ${res.clean.vector_chunks} / 隔离 ${res.clean.quarantine} / 冲突 ${res.clean.conflicts}${importMsg}`,
    );
    await load();
    await loadClean();
  } catch (e: any) {
    message.error(e?.message ?? '清洗失败');
  } finally {
    cleaning.value = false;
  }
}

async function doImportCleaned() {
  importing.value = true;
  try {
    const stats = await importCleaned(includeTierC.value, 0);
    lastImport.value = stats;
    message.success(
      `hf_data 已接入：nodes=${stats.nodes} edges=${stats.edges} chunks=${stats.chunks}`,
    );
  } catch (e: any) {
    message.error(e?.message ?? '导入失败');
  } finally {
    importing.value = false;
  }
}

function beforeUpload(_file: any) {
  fileList.value = [_file];
  return false;
}

function statusColor(s: string) {
  return s === 'done' ? 'green' : s === 'failed' ? 'red' : 'orange';
}

function stepStatus(s: string) {
  return s === 'done'
    ? 'finish'
    : s === 'skipped' || s === 'failed'
      ? 'error'
      : 'process';
}

function fmtTime(t: string) {
  return t?.replace('T', ' ').slice(0, 19);
}
</script>

<template>
  <Page>
    <div class="ing-wrap">
      <ProjectTasks />
      <ACard :body-style="{ padding: '16px 20px' }">
        <div class="ing-title">数据集清洗 · hf_data</div>
        <div class="ing-sub">
          数据根目录只读扫描 → 隔离（Q）/ 去重（D）/ 冲突标注（C）/ 规范化（N）→
          产出落盘后可一键接入知识图谱与向量库（默认含 tier C：CPS
          架构/SRS/PY*；隔离区不进正库）。
        </div>
        <div class="path-box">
          <div>
            <span class="path-label">数据源</span>
            <code class="mono">{{
              manifest?.root || manifest?.dataset_root || 'hf_data（仓库根目录）'
            }}</code>
          </div>
          <div v-if="manifest?.out_dir">
            <span class="path-label">产出目录</span>
            <code class="mono">{{ manifest.out_dir }}</code>
          </div>
        </div>
        <div class="ing-form">
          <ACheckbox v-model:checked="doImport">清洗后立即接入图谱/向量</ACheckbox>
          <ACheckbox v-model:checked="includeTierC">
            包含 tier C（CPS 合成语料，含跨境汇出关键路径）
          </ACheckbox>
          <AButton :loading="cleaning" type="primary" @click="doClean">
            清洗并接入 hf_data
          </AButton>
          <AButton :loading="importing" @click="doImportCleaned">
            仅接入已有清洗产物
          </AButton>
        </div>
        <div v-if="manifest?.exists" class="clean-stats">
          <ATag color="blue">三元组 {{ manifest.kg_triples }}</ATag>
          <ATag color="blue">chunk {{ manifest.vector_chunks }}</ATag>
          <ATag color="orange">隔离 {{ manifest.quarantine }}</ATag>
          <ATag color="purple">冲突 {{ manifest.conflicts ?? 0 }}</ATag>
          <span class="muted">{{ fmtTime(manifest.generated_at) }}</span>
        </div>
        <div v-if="lastImport" class="clean-stats">
          <ATag color="green">已接入 nodes {{ lastImport.nodes }}</ATag>
          <ATag color="green">edges {{ lastImport.edges }}</ATag>
          <ATag color="green">chunks {{ lastImport.chunks }}</ATag>
        </div>
        <div v-else-if="!manifest?.exists" class="muted mt8">
          尚未生成清洗产物，请先点击「清洗并接入 hf_data」。
        </div>
      </ACard>

      <ACard
        v-if="quarantine.length || conflicts.length"
        class="mt"
        :body-style="{ padding: '12px' }"
        title="清洗台账预览"
      >
        <div v-if="quarantine.length" class="section">
          <div class="sec-title">隔离区（quarantine）</div>
          <ATable
            :columns="quarColumns"
            :data-source="quarantine"
            :pagination="{ pageSize: 5 }"
            row-key="path"
            size="small"
          />
        </div>
        <div v-if="conflicts.length" class="section">
          <div class="sec-title">冲突台账（conflict_ledger）</div>
          <ATable
            :columns="conflictColumns"
            :data-source="conflicts"
            :pagination="{ pageSize: 5 }"
            row-key="conflict_id"
            size="small"
          />
        </div>
      </ACard>

      <ACard :body-style="{ padding: '16px 20px' }" class="mt">
        <div class="ing-title">单文件知识接入</div>
        <div class="ing-sub">
          上传素材自动执行六步：parse → clean（隔离预检）→ tag → review → merge → index
        </div>
        <div class="ing-form">
          <ASelect
            v-model:value="sourceType"
            :options="SOURCE_TYPES"
            style="width: 280px"
          />
          <AUpload
            :before-upload="beforeUpload"
            :file-list="fileList"
            :max-count="1"
            accept=".csv,.xlsx,.json,.md,.txt,.cbl"
          >
            <AButton>选择文件</AButton>
          </AUpload>
          <AButton :loading="uploading" type="primary" @click="doUpload">
            开始接入
          </AButton>
        </div>
      </ACard>

      <ACard
        v-if="lastJob?.steps?.length"
        :body-style="{ padding: '16px 20px' }"
        class="mt"
        title="最近一次任务步骤"
      >
        <ASteps :current="lastJob.steps.length" size="small">
          <AStep
            v-for="s in lastJob.steps"
            :key="s.step"
            :description="s.detail"
            :status="stepStatus(s.status)"
            :title="s.step"
          />
        </ASteps>
      </ACard>

      <ACard class="mt" :body-style="{ padding: '12px' }" title="接入任务历史">
        <ATable
          :columns="columns"
          :data-source="jobs"
          :pagination="{ pageSize: 8 }"
          row-key="job_id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <ATag :color="statusColor(record.status)">{{ record.status }}</ATag>
            </template>
            <template v-else-if="column.key === 'object_keys'">
              <span class="mono">
                {{ (record.object_keys ?? []).join(', ') }}
              </span>
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ fmtTime(record.created_at) }}
            </template>
          </template>
          <template #emptyText>
            <AEmpty description="暂无接入任务" />
          </template>
        </ATable>
      </ACard>
    </div>
  </Page>
</template>

<style lang="scss" scoped>
.ing-wrap {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.mt {
  margin-top: 12px;
}

.mt8 {
  margin-top: 8px;
}

.ing-title {
  font-size: 16px;
  font-weight: 600;
}

.ing-sub {
  margin: 4px 0 14px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.ing-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.path-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: hsl(var(--muted) / 0.35);
  border-radius: 6px;
}

.path-label {
  display: inline-block;
  min-width: 64px;
  margin-right: 8px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.clean-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
}

.muted {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.section {
  margin-bottom: 16px;
}

.sec-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}

.mono {
  font-family: monospace;
  font-size: 12px;
}
</style>
