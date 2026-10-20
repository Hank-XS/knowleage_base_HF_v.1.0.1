<script lang="ts" setup>
import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Card as ACard,
  Empty as AEmpty,
  InputSearch as AInputSearch,
  Select as ASelect,
  Spin as ASpin,
  message,
} from 'ant-design-vue';

import {
  getKmChunks,
  listKmDocs,
  listKmLibraries,
  listKmVersions,
} from '#/api/kb';

defineOptions({ name: 'KnowledgeChunk' });

const loading = ref(false);
const kb = ref('');
const version = ref('');
const docId = ref<string>();
const chunkKeyword = ref('');
const kbOptions = ref<{ label: string; value: string }[]>([]);
const docOptions = ref<{ label: string; value: string }[]>([]);
const versionOptions = ref<{ label: string; value: string }[]>([]);
const content = ref('');
const chunks = ref<any[]>([]);

const filteredChunks = computed(() => {
  const kw = chunkKeyword.value.trim().toLowerCase();
  if (!kw) return chunks.value;
  return chunks.value.filter(
    (c) =>
      c.id.toLowerCase().includes(kw) ||
      (c.title || '').toLowerCase().includes(kw) ||
      (c.text || '').toLowerCase().includes(kw),
  );
});

async function loadLibs() {
  const libs = await listKmLibraries();
  kbOptions.value = libs.map((l) => ({ label: l.title, value: l.key }));
  if (!kb.value && libs[0]) kb.value = libs[0].key;
}

async function loadDocs() {
  if (!kb.value) return;
  const res = await listKmDocs({ kb: kb.value, page: 1, page_size: 100 });
  docOptions.value = (res.items || []).map((d) => ({
    label: `${d.name}.${d.type}`,
    value: d.id,
  }));
  if (!docOptions.value.find((d) => d.value === docId.value)) {
    docId.value = docOptions.value[0]?.value;
  }
}

async function loadDetail() {
  if (!docId.value) {
    content.value = '';
    chunks.value = [];
    return;
  }
  loading.value = true;
  try {
    const vers = await listKmVersions(docId.value);
    versionOptions.value = vers.map((v) => ({
      label: v.version,
      value: v.version,
    }));
    if (!version.value || !vers.find((v) => v.version === version.value)) {
      version.value = vers[vers.length - 1]?.version || '';
    }
    const data = await getKmChunks(docId.value, {
      version: version.value || undefined,
    });
    content.value = data.content || '';
    chunks.value = data.chunks || [];
    if (!version.value) version.value = data.version;
  } catch (e: any) {
    message.error(e?.message || '加载切片失败');
  } finally {
    loading.value = false;
  }
}

watch(kb, async () => {
  docId.value = undefined;
  await loadDocs();
  await loadDetail();
});
watch([docId, version], () => loadDetail());

onMounted(async () => {
  await loadLibs();
  await loadDocs();
  await loadDetail();
});
</script>

<template>
  <Page content-class="km-page">
    <div class="head">
      <h2>切片查看</h2>
      <p>可视化查看文档切片效果</p>
    </div>
    <div class="filters">
      <ASelect v-model:value="kb" style="width: 220px" :options="kbOptions" placeholder="选择知识库" />
      <ASelect v-model:value="version" style="width: 160px" :options="versionOptions" placeholder="选择版本" />
      <ASelect v-model:value="docId" style="width: 320px" allow-clear :options="docOptions" placeholder="选择文档" />
    </div>
    <ASpin :spinning="loading">
      <div class="panes">
        <ACard class="pane">
          <template #title>
            <div class="pane-title">
              <span>原始文档</span>
              <span class="muted">{{ content.length }} 字符</span>
            </div>
          </template>
          <pre v-if="content" class="doc-body">{{ content }}</pre>
          <AEmpty v-else description="请先选择知识库、版本和文档" />
        </ACard>
        <ACard class="pane">
          <template #title>
            <div class="pane-title">
              <span>切片列表</span>
              <span class="muted">{{ filteredChunks.length }} 个 Chunk</span>
            </div>
          </template>
          <AInputSearch
            v-model:value="chunkKeyword"
            placeholder="搜索切片ID / 标题"
            enter-button="搜索"
            style="margin-bottom: 12px"
          />
          <div v-if="filteredChunks.length" class="chunk-list">
            <div v-for="c in filteredChunks" :key="c.id" class="chunk-item">
              <div class="chunk-head">
                <strong>{{ c.id.slice(0, 8) }}</strong>
                <span>{{ c.title }}</span>
                <span class="muted">{{ c.start }}-{{ c.end }}</span>
              </div>
              <p>{{ c.text }}</p>
            </div>
          </div>
          <AEmpty v-else description="该文档暂无切片" />
        </ACard>
      </div>
    </ASpin>
  </Page>
</template>

<style scoped>
.head h2 { margin: 0; font-size: 20px; }
.head p { margin: 4px 0 14px; color: #8c8c8c; font-size: 13px; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 520px; }
.pane { border-radius: 10px; min-height: 520px; }
.pane-title { display: flex; justify-content: space-between; width: 100%; }
.muted { color: #8c8c8c; font-weight: 400; font-size: 13px; }
.doc-body {
  white-space: pre-wrap; background: #f7f8fa; padding: 12px; border-radius: 8px;
  max-height: 480px; overflow: auto; font-size: 13px; margin: 0;
}
.chunk-list { display: flex; flex-direction: column; gap: 10px; max-height: 440px; overflow: auto; }
.chunk-item { border: 1px solid #f0f0f0; border-radius: 8px; padding: 10px 12px; background: #fafafa; }
.chunk-head { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; font-size: 13px; }
.chunk-item p { margin: 0; color: #595959; font-size: 13px; line-height: 1.5; }
@media (max-width: 960px) { .panes { grid-template-columns: 1fr; } }
</style>
