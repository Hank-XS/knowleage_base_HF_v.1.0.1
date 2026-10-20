<script lang="ts" setup>
import { onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  RadioButton as ARadioButton,
  RadioGroup as ARadioGroup,
  Select as ASelect,
  Space as ASpace,
  Spin as ASpin,
  message,
} from 'ant-design-vue';

import {
  bumpKmVersion,
  getKmDiff,
  listKmDocs,
  listKmLibraries,
  listKmVersions,
} from '#/api/kb';

defineOptions({ name: 'KnowledgeDiff' });

const loading = ref(false);
const kb = ref('');
const docId = ref('');
const oldVer = ref('');
const newVer = ref('');
const viewMode = ref<'side' | 'merged'>('side');
const kbOptions = ref<{ label: string; value: string }[]>([]);
const docOptions = ref<{ label: string; value: string }[]>([]);
const versionOptions = ref<{ label: string; value: string }[]>([]);
const docName = ref('');
const stats = ref({ added: 0, removed: 0, modified: 0 });
const rows = ref<Array<{ left?: string; right?: string; type: string }>>([]);

async function loadLibs() {
  const libs = await listKmLibraries();
  kbOptions.value = libs.map((l) => ({ label: l.title, value: l.key }));
  if (!kb.value && libs[0]) kb.value = libs[0].key;
}

async function loadDocs() {
  if (!kb.value) return;
  const res = await listKmDocs({ kb: kb.value, page_size: 100 });
  docOptions.value = (res.items || []).map((d) => ({
    label: `${d.name}.${d.type}  版本: ${d.version}`,
    value: d.id,
  }));
  if (!docOptions.value.find((d) => d.value === docId.value)) {
    docId.value = docOptions.value[0]?.value || '';
  }
}

async function loadVersions() {
  if (!docId.value) return;
  const vers = await listKmVersions(docId.value);
  versionOptions.value = vers.map((v) => ({ label: v.version, value: v.version }));
  if (vers.length === 1) {
    // 自动补一个版本便于对比演示
    try {
      await bumpKmVersion(docId.value, `${vers[0].version}-diff`, '自动生成对比版本');
      const again = await listKmVersions(docId.value);
      versionOptions.value = again.map((v) => ({
        label: v.version,
        value: v.version,
      }));
      oldVer.value = again[0]?.version || '';
      newVer.value = again[again.length - 1]?.version || '';
      return;
    } catch {
      /* ignore */
    }
  }
  oldVer.value = vers[0]?.version || '';
  newVer.value = vers[vers.length - 1]?.version || oldVer.value;
}

async function loadDiff() {
  if (!docId.value || !oldVer.value || !newVer.value) {
    rows.value = [];
    return;
  }
  loading.value = true;
  try {
    const data = await getKmDiff(docId.value, oldVer.value, newVer.value);
    docName.value = `${data.doc.name}.${data.doc.type}`;
    stats.value = data.stats;
    rows.value = data.rows || [];
  } catch (e: any) {
    message.error(e?.message || '对比失败');
  } finally {
    loading.value = false;
  }
}

function swapVersions() {
  const t = oldVer.value;
  oldVer.value = newVer.value;
  newVer.value = t;
}

watch(kb, async () => {
  await loadDocs();
  await loadVersions();
  await loadDiff();
});
watch(docId, async () => {
  await loadVersions();
  await loadDiff();
});
watch([oldVer, newVer], () => loadDiff());

onMounted(async () => {
  await loadLibs();
  await loadDocs();
  await loadVersions();
  await loadDiff();
});
</script>

<template>
  <Page content-class="km-page">
    <div class="head">
      <h2>版本对比</h2>
      <p>对比文档不同版本的内容差异</p>
    </div>
    <ACard class="card">
      <div class="selectors">
        <ASelect v-model:value="kb" style="min-width: 220px; flex: 1" :options="kbOptions" />
        <ASelect v-model:value="docId" style="min-width: 320px; flex: 1" :options="docOptions" />
      </div>
      <div class="ver-row">
        <ASpace>
          <span>旧版本</span>
          <ASelect v-model:value="oldVer" style="width: 140px" :options="versionOptions" />
          <AButton @click="swapVersions">⇄</AButton>
          <span>新版本</span>
          <ASelect v-model:value="newVer" style="width: 140px" :options="versionOptions" />
        </ASpace>
        <ASpace class="stats">
          <span class="add">新增 {{ stats.added }} 行</span>
          <span class="del">删除 {{ stats.removed }} 行</span>
          <span class="mod">修改 {{ stats.modified }} 行</span>
        </ASpace>
      </div>
    </ACard>

    <ASpin :spinning="loading">
      <ACard class="card">
        <template #title>
          <div class="viewer-head">
            <span>📄 {{ docName || '文档' }}</span>
            <ASpace>
              <ARadioGroup v-model:value="viewMode" button-style="solid" size="small">
                <ARadioButton value="side">并排</ARadioButton>
                <ARadioButton value="merged">合并</ARadioButton>
              </ARadioGroup>
              <span class="muted">{{ oldVer }} ⇄ {{ newVer }}</span>
            </ASpace>
          </div>
        </template>
        <div v-if="rows.length">
          <div v-if="viewMode === 'side'" class="side">
            <div v-for="(row, idx) in rows" :key="idx" class="side-row" :class="row.type">
              <div class="col">{{ row.left ?? '' }}</div>
              <div class="col">{{ row.right ?? '' }}</div>
            </div>
          </div>
          <div v-else class="merged">
            <div v-for="(row, idx) in rows" :key="idx" class="merged-row" :class="row.type">
              <template v-if="row.type === 'del'">- {{ row.left }}</template>
              <template v-else-if="row.type === 'add'">+ {{ row.right }}</template>
              <template v-else-if="row.type === 'mod'">
                <div class="del-line">- {{ row.left }}</div>
                <div class="add-line">+ {{ row.right }}</div>
              </template>
              <template v-else>{{ row.left }}</template>
            </div>
          </div>
        </div>
        <AEmpty v-else description="请选择可对比版本的文档" />
      </ACard>
    </ASpin>
  </Page>
</template>

<style scoped>
.head h2 { margin: 0; font-size: 20px; }
.head p { margin: 4px 0 14px; color: #8c8c8c; font-size: 13px; }
.card { border-radius: 10px; margin-bottom: 12px; }
.selectors { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.ver-row { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.stats .add { color: #389e0d; }
.stats .del { color: #cf1322; }
.stats .mod { color: #d48806; }
.viewer-head { display: flex; justify-content: space-between; width: 100%; gap: 12px; }
.muted { color: #8c8c8c; font-size: 13px; }
.side {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; max-height: 480px; overflow: auto; border: 1px solid #f0f0f0; border-radius: 8px;
}
.side-row { display: grid; grid-template-columns: 1fr 1fr; }
.side-row .col { padding: 2px 8px; white-space: pre-wrap; border-right: 1px solid #f0f0f0; min-height: 20px; }
.side-row.add .col:last-child, .merged-row.add, .add-line { background: #f6ffed; }
.side-row.del .col:first-child, .merged-row.del, .del-line { background: #fff1f0; }
.side-row.mod .col { background: #fff7e6; }
.merged {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; max-height: 480px; overflow: auto; border: 1px solid #f0f0f0; border-radius: 8px;
}
.merged-row { padding: 2px 8px; white-space: pre-wrap; }
</style>
