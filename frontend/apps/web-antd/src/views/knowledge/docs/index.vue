<script lang="ts" setup>
import type { KmDoc, KmLibrary } from '#/api/kb';

import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Empty as AEmpty,
  InputSearch as AInputSearch,
  Modal,
  Select as ASelect,
  Space as ASpace,
  Spin as ASpin,
  Table as ATable,
  Tag as ATag,
  Tooltip as ATooltip,
  Tree as ATree,
  message,
} from 'ant-design-vue';

import {
  batchKmDocStatus,
  deleteKmDoc,
  getKmDoc,
  listKmDocs,
  listKmLibraries,
  syncKmDataset,
} from '#/api/kb';

defineOptions({ name: 'KnowledgeDocs' });

const router = useRouter();

const loading = ref(false);
const folderKeyword = ref('');
const libraries = ref<KmLibrary[]>([]);
const selectedKb = ref('');
const docKeyword = ref('');
const filterType = ref<string>();
const filterStatus = ref<string>();
const filterVersion = ref<string>();
const filterVector = ref<string>();
const filterOfficial = ref<string>();
const filterSecurity = ref<string>();
const page = ref(1);
const pageSize = 10;
const total = ref(0);
const docs = ref<KmDoc[]>([]);
const selectedRowKeys = ref<string[]>([]);
const previewOpen = ref(false);
const previewDoc = ref<KmDoc | null>(null);
const syncing = ref(false);

const filteredLibraries = computed(() => {
  const kw = folderKeyword.value.trim().toLowerCase();
  if (!kw) return libraries.value;
  const match = (f: KmLibrary): KmLibrary | null => {
    const children = (f.children || [])
      .map(match)
      .filter(Boolean) as KmLibrary[];
    if (f.title.toLowerCase().includes(kw) || children.length) {
      return { ...f, children: children.length ? children : f.children };
    }
    return null;
  };
  return libraries.value.map(match).filter(Boolean) as KmLibrary[];
});

const treeData = computed(() =>
  filteredLibraries.value.map((f) => ({
    key: f.key,
    title: f.title,
    count: f.count,
    children: (f.children || []).map((c) => ({
      key: c.key,
      title: c.title,
      count: c.count,
      isLeaf: true,
    })),
  })),
);

const currentKbTitle = computed(() => {
  const top = selectedKb.value.split('/')[0];
  const found = libraries.value.find((f) => f.key === top);
  if (found) {
    if (selectedKb.value.includes('/')) {
      const child = found.children?.find((c) => c.key === selectedKb.value);
      return child ? `${found.title} / ${child.title}` : found.title;
    }
    return found.title;
  }
  return selectedKb.value || '全部知识库';
});

const columns = [
  { title: '文档名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '类型', dataIndex: 'type', key: 'type', width: 70 },
  { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '向量化', dataIndex: 'vectorized', key: 'vectorized', width: 100 },
  { title: '官方属性', dataIndex: 'official', key: 'official', width: 100 },
  { title: '安全等级', dataIndex: 'security', key: 'security', width: 90 },
  { title: '大小', dataIndex: 'size', key: 'size', width: 70 },
  { title: '上传时间', dataIndex: 'uploadedAt', key: 'uploadedAt', width: 170 },
  { title: '操作', key: 'actions', width: 140, fixed: 'right' },
];

function statusLabel(s: string) {
  return ({ draft: '草稿', review: '审核中', published: '已发布' } as any)[s] || s;
}
function securityLabel(s: string) {
  return (
    ({
      public: '公开',
      internal: '内部',
      secret: '秘密',
      confidential: '机密',
    } as any)[s] || s
  );
}

async function loadLibraries() {
  try {
    libraries.value = await listKmLibraries();
    if (!selectedKb.value && libraries.value[0]) {
      selectedKb.value = libraries.value[0].key;
    }
  } catch (e: any) {
    message.error(e?.message || '加载知识库失败');
    libraries.value = [];
  }
}

async function loadDocs() {
  loading.value = true;
  try {
    const res = await listKmDocs({
      kb: selectedKb.value,
      keyword: docKeyword.value || undefined,
      type: filterType.value || undefined,
      status: filterStatus.value || undefined,
      version: filterVersion.value || undefined,
      vectorized: filterVector.value || undefined,
      official: filterOfficial.value || undefined,
      security: filterSecurity.value || undefined,
      page: page.value,
      page_size: pageSize,
    });
    docs.value = res.items || [];
    total.value = res.total || 0;
  } catch (e: any) {
    message.error(e?.message || '加载文档失败');
    docs.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

function onSelectKb(keys: (string | number)[]) {
  if (keys[0]) {
    selectedKb.value = String(keys[0]);
    page.value = 1;
  }
}

function goUpload() {
  router.push({ path: '/knowledge/upload', query: { kb: selectedKb.value } });
}

async function openPreview(doc: KmDoc) {
  try {
    previewDoc.value = await getKmDoc(doc.id);
    previewOpen.value = true;
  } catch {
    message.error('预览失败');
  }
}

function onDelete(doc: KmDoc) {
  Modal.confirm({
    title: '确认删除',
    content: `确定删除文档「${doc.name}」？`,
    onOk: async () => {
      await deleteKmDoc(doc.id);
      message.success('已删除');
      await loadDocs();
      await loadLibraries();
    },
  });
}

async function batchAudit(submit: boolean) {
  if (!selectedRowKeys.value.length) {
    message.warning('请先勾选文档');
    return;
  }
  const res = await batchKmDocStatus({
    action: submit ? 'submit' : 'audit',
    doc_ids: selectedRowKeys.value,
    status: submit ? 'review' : 'published',
  });
  message.success(`已更新 ${res.updated} 条`);
  selectedRowKeys.value = [];
  await loadDocs();
}

async function doSync() {
  syncing.value = true;
  try {
    const res = await syncKmDataset(true);
    message.success(
      res.synced
        ? `同步完成，文档 ${res.docs} 条`
        : `同步结果：${res.reason || 'ok'}`,
    );
    await loadLibraries();
    await loadDocs();
  } catch (e: any) {
    message.error(e?.message || '同步失败');
  } finally {
    syncing.value = false;
  }
}

watch(
  [
    selectedKb,
    filterType,
    filterStatus,
    filterVersion,
    filterVector,
    filterOfficial,
    filterSecurity,
  ],
  () => {
    page.value = 1;
    loadDocs();
  },
);

onMounted(async () => {
  await loadLibraries();
  await loadDocs();
});
</script>

<template>
  <Page auto-content-height content-class="km-page">
    <div class="km-docs">
      <aside class="km-side">
        <div class="km-side-head">
          <span>知识库列表</span>
          <ATooltip title="从 hf_data 强制同步">
            <AButton type="link" size="small" :loading="syncing" @click="doSync">
              同步
            </AButton>
          </ATooltip>
        </div>
        <AInputSearch
          v-model:value="folderKeyword"
          placeholder="搜索知识库"
          enter-button="搜索"
          size="middle"
        />
        <ASpace class="km-side-actions">
          <AButton size="small" @click="batchAudit(true)">批量提交审核</AButton>
          <AButton size="small" type="primary" ghost @click="batchAudit(false)">
            批量审核
          </AButton>
        </ASpace>
        <ATree
          v-if="treeData.length"
          :tree-data="treeData"
          :selected-keys="selectedKb ? [selectedKb] : []"
          default-expand-all
          block-node
          @select="onSelectKb"
        >
          <template #title="{ title, count, dataRef }">
            <div class="km-tree-node">
              <span>{{ title }}</span>
              <span class="km-tree-count">{{ count ?? dataRef?.count }}</span>
            </div>
          </template>
        </ATree>
        <AEmpty v-else description="无知识库，请先同步" />
      </aside>

      <section class="km-main">
        <div class="km-main-head">
          <div>
            <h2>{{ currentKbTitle }}</h2>
            <p>管理知识库中的所有文档，支持上传、编辑和删除</p>
          </div>
          <AButton type="primary" @click="goUpload">+ 新增上传</AButton>
        </div>

        <div class="km-filters">
          <AInputSearch
            v-model:value="docKeyword"
            placeholder="搜索文档名称..."
            enter-button="搜索"
            style="width: 260px"
            @search="
              () => {
                page = 1;
                loadDocs();
              }
            "
          />
          <ASelect
            v-model:value="filterType"
            allow-clear
            placeholder="全部类型"
            style="width: 120px"
            :options="[
              { label: 'md', value: 'md' },
              { label: 'cbl', value: 'cbl' },
              { label: 'yaml', value: 'yaml' },
              { label: 'json', value: 'json' },
              { label: 'jcl', value: 'jcl' },
              { label: 'csv', value: 'csv' },
              { label: 'py', value: 'py' },
              { label: 'java', value: 'java' },
            ]"
          />
          <ASelect
            v-model:value="filterStatus"
            allow-clear
            placeholder="全部状态"
            style="width: 120px"
            :options="[
              { label: '草稿', value: 'draft' },
              { label: '审核中', value: 'review' },
              { label: '已发布', value: 'published' },
            ]"
          />
          <ASelect
            v-model:value="filterVersion"
            allow-clear
            placeholder="全部版本"
            style="width: 120px"
            :options="[
              { label: 'v1.0', value: 'v1.0' },
              { label: 'v1.1', value: 'v1.1' },
              { label: 'v2.0', value: 'v2.0' },
              { label: 'v3.2.1', value: 'v3.2.1' },
            ]"
          />
          <ASelect
            v-model:value="filterVector"
            allow-clear
            placeholder="全部向量化状态"
            style="width: 150px"
            :options="[
              { label: '已向量化', value: 'yes' },
              { label: '未向量化', value: 'no' },
            ]"
          />
          <ASelect
            v-model:value="filterOfficial"
            allow-clear
            placeholder="全部官方属性"
            style="width: 140px"
            :options="[
              { label: '官方知识', value: 'yes' },
              { label: '非官方知识', value: 'no' },
            ]"
          />
          <ASelect
            v-model:value="filterSecurity"
            allow-clear
            placeholder="全部安全等级"
            style="width: 140px"
            :options="[
              { label: '公开', value: 'public' },
              { label: '内部', value: 'internal' },
              { label: '秘密', value: 'secret' },
              { label: '机密', value: 'confidential' },
            ]"
          />
        </div>

        <div class="km-table-card">
          <div class="km-table-title">
            文档列表
            <span>共 {{ total }} 条</span>
          </div>
          <ASpin :spinning="loading">
            <ATable
              row-key="id"
              size="middle"
              :columns="columns"
              :data-source="docs"
              :row-selection="{
                selectedRowKeys,
                onChange: (keys) => (selectedRowKeys = keys.map(String)),
              }"
              :pagination="{
                current: page,
                pageSize,
                total,
                showSizeChanger: false,
                showTotal: (t, range) =>
                  `显示 ${range[0]}-${range[1]} 条，共 ${t} 条`,
                onChange: (p) => {
                  page = p;
                  loadDocs();
                },
              }"
              :scroll="{ x: 1100 }"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'name'">
                  <a @click="openPreview(record as KmDoc)">{{ record.name }}</a>
                </template>
                <template v-else-if="column.key === 'status'">
                  {{ statusLabel(record.status) }}
                </template>
                <template v-else-if="column.key === 'vectorized'">
                  <span :class="record.vectorized ? 'ok' : 'muted'">
                    {{ record.vectorized ? '已向量化' : '未向量化' }}
                  </span>
                </template>
                <template v-else-if="column.key === 'official'">
                  <ATag :color="record.official ? 'blue' : 'default'">
                    {{ record.official ? '官方知识' : '非官方知识' }}
                  </ATag>
                </template>
                <template v-else-if="column.key === 'security'">
                  <ATag
                    :color="record.security === 'public' ? 'success' : 'orange'"
                  >
                    {{ securityLabel(record.security) }}
                  </ATag>
                </template>
                <template v-else-if="column.key === 'actions'">
                  <ASpace>
                    <AButton
                      type="link"
                      size="small"
                      @click="openPreview(record as KmDoc)"
                    >
                      预览
                    </AButton>
                    <AButton
                      type="link"
                      danger
                      size="small"
                      @click="onDelete(record as KmDoc)"
                    >
                      删除
                    </AButton>
                  </ASpace>
                </template>
              </template>
            </ATable>
          </ASpin>
        </div>
      </section>
    </div>

    <Modal
      v-model:open="previewOpen"
      :title="previewDoc?.name"
      width="720px"
      :footer="null"
    >
      <pre class="km-preview">{{ previewDoc?.content || '（无正文预览）' }}</pre>
    </Modal>
  </Page>
</template>

<style scoped>
.km-docs {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 12px;
  min-height: 640px;
}
.km-side,
.km-main,
.km-table-card {
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 10px;
}
.km-side {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
}
.km-side-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.km-tree-node {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}
.km-tree-count {
  color: #8c8c8c;
  font-size: 12px;
}
.km-main {
  padding: 16px 18px;
  overflow: auto;
}
.km-main-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
}
.km-main-head h2 {
  margin: 0;
  font-size: 20px;
}
.km-main-head p {
  margin: 4px 0 0;
  color: #8c8c8c;
  font-size: 13px;
}
.km-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.km-table-card {
  padding: 8px 12px 4px;
}
.km-table-title {
  display: flex;
  justify-content: space-between;
  padding: 8px 4px 12px;
  font-weight: 600;
}
.km-table-title span {
  font-weight: 400;
  color: #8c8c8c;
}
.muted {
  color: #8c8c8c;
}
.ok {
  color: #389e0d;
}
.km-preview {
  white-space: pre-wrap;
  background: #f7f8fa;
  padding: 12px;
  border-radius: 8px;
  max-height: 480px;
  overflow: auto;
  font-size: 13px;
}
</style>
