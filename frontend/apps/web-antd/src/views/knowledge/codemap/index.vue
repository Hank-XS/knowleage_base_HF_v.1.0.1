<script lang="ts" setup>
import { onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Card as ACard,
  Empty as AEmpty,
  RadioButton as ARadioButton,
  RadioGroup as ARadioGroup,
  Select as ASelect,
  Spin as ASpin,
  Tag as ATag,
  message,
} from 'ant-design-vue';

import { getKmCodeMap, listKmCodeFiles, listKmLibraries } from '#/api/kb';

defineOptions({ name: 'KnowledgeCodeMap' });

const loading = ref(false);
const direction = ref<'code2doc' | 'doc2code'>('code2doc');
const kb = ref('');
const fileKey = ref('');
const version = ref('');
const kbOptions = ref<{ label: string; value: string }[]>([]);
const fileOptions = ref<{ label: string; value: string }[]>([]);
const content = ref('');
const label = ref('');
const related = ref<Array<{ id: string; name: string; section: string }>>([]);
const symbol = ref('');

async function loadLibs() {
  const libs = await listKmLibraries();
  kbOptions.value = libs.map((l) => ({ label: l.title, value: l.key }));
  // 代码多在 02_code_assets
  const codeLib = libs.find((l) => l.key.includes('code'));
  if (!kb.value) kb.value = codeLib?.key || libs[0]?.key || '';
}

async function loadFiles() {
  const files = await listKmCodeFiles(kb.value);
  fileOptions.value = files.map((f) => ({ label: f.label, value: f.key }));
  if (!fileOptions.value.find((f) => f.value === fileKey.value)) {
    fileKey.value = fileOptions.value[0]?.value || '';
  }
}

async function loadMap() {
  if (!fileKey.value) {
    content.value = '';
    related.value = [];
    return;
  }
  loading.value = true;
  try {
    const data = await getKmCodeMap(fileKey.value);
    content.value = data.file?.content || '';
    label.value = data.file?.label || '';
    version.value = data.file?.version || '';
    related.value = data.relatedDocs || [];
    symbol.value = data.symbol || '';
  } catch (e: any) {
    message.error(e?.message || '加载映射失败');
  } finally {
    loading.value = false;
  }
}

watch(kb, async () => {
  await loadFiles();
  await loadMap();
});
watch(fileKey, () => loadMap());

onMounted(async () => {
  await loadLibs();
  await loadFiles();
  await loadMap();
});
</script>

<template>
  <Page content-class="km-page">
    <div class="head">
      <h2>代码文档映射</h2>
      <p>展示代码片段与文档章节的双向映射关系</p>
    </div>
    <div class="controls">
      <ARadioGroup v-model:value="direction" button-style="solid">
        <ARadioButton value="code2doc">代码 → 文档</ARadioButton>
        <ARadioButton value="doc2code">文档 → 代码</ARadioButton>
      </ARadioGroup>
      <div class="filters">
        <ASelect v-model:value="kb" style="width: 200px" :options="kbOptions" />
        <ASelect v-model:value="fileKey" style="width: 280px" :options="fileOptions" />
        <ASelect
          v-model:value="version"
          style="width: 120px"
          :options="version ? [{ label: version, value: version }] : []"
        />
      </div>
    </div>

    <ASpin :spinning="loading">
      <div class="panes">
        <ACard class="pane">
          <template #title>
            <span>💻 {{ label || '代码' }} {{ symbol ? `· ${symbol}` : '' }}</span>
          </template>
          <pre class="code">{{ content }}</pre>
        </ACard>
        <ACard class="pane">
          <template #title>
            <div class="pane-title">
              <span>关联文档</span>
              <ATag color="blue">{{ related.length }}</ATag>
            </div>
          </template>
          <div v-if="related.length" class="rel-list">
            <div v-for="d in related" :key="d.id" class="rel-item">
              <div class="rel-name">📄 {{ d.name }}</div>
              <div class="rel-sec">{{ d.section }}</div>
              <ATag :color="direction === 'code2doc' ? 'processing' : 'purple'">
                {{ direction === 'code2doc' ? '代码引用' : '文档回溯' }}
              </ATag>
            </div>
          </div>
          <AEmpty v-else description="未找到映射：该文件可能未被任何文档引用，或名称不匹配" />
        </ACard>
      </div>
    </ASpin>
  </Page>
</template>

<style scoped>
.head h2 { margin: 0; font-size: 20px; }
.head p { margin: 4px 0 14px; color: #8c8c8c; font-size: 13px; }
.controls { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; }
.panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; min-height: 520px; }
.pane { border-radius: 10px; min-height: 520px; }
.pane-title { display: flex; justify-content: space-between; width: 100%; align-items: center; }
.code {
  margin: 0; background: #0f172a; color: #e2e8f0; padding: 14px; border-radius: 8px;
  font-size: 12px; line-height: 1.55; max-height: 480px; overflow: auto; white-space: pre;
}
.rel-list { display: flex; flex-direction: column; gap: 10px; }
.rel-item { border: 1px solid #f0f0f0; border-radius: 8px; padding: 12px; background: #fafafa; }
.rel-name { font-weight: 600; margin-bottom: 4px; }
.rel-sec { color: #8c8c8c; font-size: 13px; margin-bottom: 8px; }
@media (max-width: 960px) { .panes { grid-template-columns: 1fr; } }
</style>
