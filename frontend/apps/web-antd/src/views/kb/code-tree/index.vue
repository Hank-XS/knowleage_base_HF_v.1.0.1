<script lang="ts" setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Col as ACol,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Input as AInput,
  Row as ARow,
  Select as ASelect,
  Spin as ASpin,
  TabPane as ATabPane,
  Tabs as ATabs,
  Tag as ATag,
  Tree as ATree,
  message,
} from 'ant-design-vue';
import { marked } from 'marked';

import {
  annotateCode,
  generateSpec,
  getCodeTree,
  getCodeWork,
  listPrompts,
  previewCodeTree,
} from '#/api/kb';

defineOptions({ name: 'KbCodeTree' });
const router = useRouter();

marked.setOptions({
  gfm: true,
  breaks: true,
});

const loading = ref(false);
const tree = ref<any[]>([]);
const stats = ref<any>(null);
const keyword = ref('');
const expandedKeys = ref<string[]>([]);
const selectedKeys = ref<string[]>([]);
const selected = ref<any>(null);
const preview = ref<any>(null);
const previewLoading = ref(false);
const nodeIndex = ref<Map<string, any>>(new Map());

const activeTab = ref('source');
const annotateLoading = ref(false);
const annotateResult = ref<any>(null);
const specLoading = ref(false);
const specResult = ref<any>(null);
const promptType = ref('program');
const promptOptions = ref<{ label: string; value: string }[]>([]);
const selectedSymbol = ref('');
const specViewMode = ref<'render' | 'raw'>('render');

const hasAnnotate = computed(() =>
  Boolean((annotateResult.value?.annotated_code || '').trim()),
);

/** DeepSeek 风格：Markdown 渲染为 HTML（仅内部生成内容） */
const specHtml = computed(() => {
  const md = String(specResult.value?.markdown || '').trim();
  if (!md) return '';
  try {
    const html = marked.parse(md, { async: false }) as string;
    // 轻量消毒：去掉脚本/事件处理器
    return html
      .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
      .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '');
  } catch {
    return `<pre>${md.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c] || c)}</pre>`;
  }
});

const KIND_TEXT: Record<string, string> = {
  dir: '目录',
  program: '程序',
  file: '文件',
  paragraph: '段',
  step: '作业步',
  procedure: '存储过程',
};

function collectKeys(nodes: any[], depth: number, acc: string[]) {
  for (const n of nodes) {
    if (n.kind === 'dir' && depth < 1) acc.push(n.key);
    if (n.children?.length && depth < 1) collectKeys(n.children, depth + 1, acc);
  }
}

function indexNodes(nodes: any[], acc: Map<string, any>) {
  for (const n of nodes) {
    acc.set(String(n.key), n);
    if (n.children?.length) indexNodes(n.children, acc);
  }
}

function filterTree(nodes: any[], q: string): any[] {
  const out: any[] = [];
  for (const n of nodes) {
    const kids = n.children ? filterTree(n.children, q) : [];
    const self = [n.title, n.program, n.path, ...(n.calls || [])]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(q);
    if (self || kids.length) {
      out.push({
        ...n,
        children: kids.length ? kids : n.children && self ? n.children : kids,
      });
    }
  }
  return out;
}

const viewTree = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  if (!q) return tree.value;
  return filterTree(tree.value, q);
});

const annotateHint = computed(() => {
  if (!selected.value) return '';
  return (
    selected.value.program ||
    selected.value.title ||
    selected.value.path ||
    ''
  );
});

const annotateLang = computed(() => {
  const lang = String(selected.value?.lang || preview.value?.path || 'cobol')
    .toLowerCase();
  if (lang.includes('java')) return 'java';
  if (lang.includes('py') || lang.includes('shell')) return 'python';
  return 'cobol';
});

function inferPromptType(node: any): string {
  const lang = String(node?.lang || '').toLowerCase();
  const path = String(node?.path || '').toLowerCase();
  if (lang === 'copybook' || path.endsWith('.cpy') || path.includes('copybook')) {
    return 'copybook';
  }
  if (lang === 'jcl' || path.endsWith('.jcl') || path.includes('/jcl/')) {
    return 'batch';
  }
  if (path.includes('interface')) return 'interface';
  return 'program';
}

async function loadPrompts() {
  try {
    const rows = (await listPrompts()) || [];
    promptOptions.value = rows
      .filter((r: any) => r.enabled !== false)
      .map((r: any) => ({
        label: r.title || r.type,
        value: r.type,
      }));
    if (
      promptOptions.value.length &&
      !promptOptions.value.some((o) => o.value === promptType.value)
    ) {
      promptType.value = promptOptions.value[0]!.value;
    }
  } catch {
    promptOptions.value = [
      { label: '程序式样书', value: 'program' },
      { label: '接口式样书', value: 'interface' },
      { label: '批处理式样书', value: 'batch' },
      { label: 'COPYBOOK 式样书', value: 'copybook' },
    ];
  }
}

async function load() {
  loading.value = true;
  try {
    const data = await getCodeTree();
    tree.value = data?.tree || [];
    stats.value = data?.stats || null;
    const acc = new Map<string, any>();
    indexNodes(tree.value, acc);
    nodeIndex.value = acc;
    const keys: string[] = [];
    collectKeys(tree.value, 0, keys);
    expandedKeys.value = keys;
  } catch (e: any) {
    message.error(e?.message ?? '加载代码树失败');
  } finally {
    loading.value = false;
  }
}

function applyWork(work: any) {
  if (work?.has_annotate && work.annotated_code) {
    annotateResult.value = {
      annotated_code: work.annotated_code,
      sources: work.annotate?.sources || [],
      notes: work.annotate?.notes || [],
      uncovered: work.annotate?.uncovered,
      disclaimer: work.annotate?.disclaimer,
    };
  } else {
    annotateResult.value = null;
  }
  if (work?.has_spec && work.spec_markdown) {
    specResult.value = {
      markdown: work.spec_markdown,
      title: work.spec?.title,
      prompt_type: work.prompt_type || work.spec?.prompt_type,
      notes: work.spec?.notes || [],
      uncovered: work.spec?.uncovered,
      disclaimer: work.spec?.disclaimer,
      sources: work.spec?.sources || work.annotate?.sources || [],
      annotated_code: work.annotated_code,
    };
    if (work.prompt_type) promptType.value = work.prompt_type;
    specViewMode.value = 'render';
  } else {
    specResult.value = null;
  }
}

async function onSelect(keys: (string | number)[]) {
  const node = nodeIndex.value.get(String(keys[0] || ''));
  selected.value = node || null;
  selectedKeys.value = keys.map(String);
  preview.value = null;
  annotateResult.value = null;
  specResult.value = null;
  selectedSymbol.value = '';
  activeTab.value = 'source';
  if (node && node.kind !== 'dir') {
    promptType.value = inferPromptType(node);
  }
  const path = node?.path as string | undefined;
  if (!path || node?.kind === 'dir') return;
  const symbol =
    node?.kind === 'paragraph' ||
    node?.kind === 'step' ||
    node?.kind === 'procedure'
      ? String(node.title || '')
      : '';
  selectedSymbol.value = symbol;
  previewLoading.value = true;
  try {
    preview.value = await previewCodeTree(path, symbol);
    const work = await getCodeWork(path, symbol);
    applyWork(work);
    if (work?.has_spec) activeTab.value = 'spec';
    else if (work?.has_annotate) activeTab.value = 'annotate';
  } catch (e: any) {
    message.error(e?.message ?? '预览失败');
  } finally {
    previewLoading.value = false;
  }
}

function onExpand(keys: (string | number)[]) {
  expandedKeys.value = keys.map(String);
}

async function doAnnotate() {
  const raw = (preview.value?.raw || '').trim();
  if (!raw) {
    message.warning('请先在左侧选择程序或段');
    return;
  }
  annotateLoading.value = true;
  activeTab.value = 'annotate';
  try {
    annotateResult.value = await annotateCode({
      code: raw,
      language: annotateLang.value,
      hint: String(annotateHint.value || ''),
      path: String(selected.value?.path || ''),
      symbol: selectedSymbol.value,
    });
    // 重新注释后旧式样书作废
    specResult.value = null;
    message.success('注释已生成并保存');
  } catch (e: any) {
    message.error(e?.message ?? '生成失败');
  } finally {
    annotateLoading.value = false;
  }
}

async function copyAnnotated() {
  const text = annotateResult.value?.annotated_code || '';
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    message.success('已复制到剪贴板');
  } catch {
    message.error('复制失败，请手动选择文本');
  }
}

async function doSpec() {
  const ann = (annotateResult.value?.annotated_code || '').trim();
  if (!ann) {
    message.warning('请先生成注释');
    return;
  }
  specLoading.value = true;
  activeTab.value = 'spec';
  try {
    const result = await generateSpec({
      code: String(preview.value?.raw || ''),
      annotated_code: ann,
      prompt_type: promptType.value,
      path: String(selected.value?.path || ''),
      symbol: selectedSymbol.value,
      language: String(selected.value?.lang || annotateLang.value),
      hint: String(annotateHint.value || ''),
    });
    specResult.value = result;
    specViewMode.value = 'render';
    message.success('式样书已生成并保存');
  } catch (e: any) {
    message.error(e?.message ?? '生成失败');
  } finally {
    specLoading.value = false;
  }
}

async function copySpec() {
  const text = specResult.value?.markdown || '';
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    message.success('已复制到剪贴板');
  } catch {
    message.error('复制失败，请手动选择文本');
  }
}

onMounted(() => {
  load();
  loadPrompts();
});
</script>

<template>
  <Page>
    <div class="ct-wrap">
      <ACard :body-style="{ padding: '16px 20px' }">
        <template #extra><AButton @click="router.push('/kb/ingest')">已上传工程与解析结果</AButton></template>
        <div class="ct-title">代码树与注释</div>
        <div class="ct-sub">
          先生成注释并落库，再选式样书类型增强生成；再次打开同一节点会加载已保存结果
        </div>
        <div v-if="stats" class="ct-stats">
          <ATag color="blue">文件 {{ stats.files }}</ATag>
          <ATag color="green">COBOL 程序 {{ stats.programs }}</ATag>
          <ATag>目录 {{ stats.dirs }}</ATag>
        </div>
      </ACard>

      <ARow class="mt" :gutter="16">
        <ACol :span="9">
          <ACard title="代码树" :body-style="{ padding: '12px 16px' }">
            <div class="ct-tools">
              <AInput
                v-model:value="keyword"
                allow-clear
                placeholder="搜索程序名 / 段名 / 路径 / CALL"
              />
              <AButton :loading="loading" @click="load">刷新</AButton>
            </div>
            <ASpin :spinning="loading">
              <ATree
                v-if="viewTree.length"
                class="ct-tree"
                :tree-data="viewTree"
                :expanded-keys="expandedKeys"
                :selected-keys="selectedKeys"
                show-line
                @expand="onExpand"
                @select="onSelect"
              />
              <AEmpty v-else description="没有匹配的代码节点" />
            </ASpin>
          </ACard>
        </ACol>

        <ACol :span="15">
          <ACard :body-style="{ padding: '12px 16px 16px' }">
            <template v-if="selected && selected.kind !== 'dir'">
              <div class="ct-head">
                <ADescriptions :column="2" size="small" bordered class="ct-desc">
                  <ADescriptionsItem label="名称">
                    {{ selected.program || selected.title }}
                  </ADescriptionsItem>
                  <ADescriptionsItem label="类型">
                    {{ KIND_TEXT[selected.kind] || selected.kind }}
                  </ADescriptionsItem>
                  <ADescriptionsItem v-if="selected.lang" label="语言">
                    {{ selected.lang }}
                  </ADescriptionsItem>
                  <ADescriptionsItem v-if="selected.lines" label="行数">
                    {{ selected.lines }}
                  </ADescriptionsItem>
                  <ADescriptionsItem label="路径" :span="2">
                    {{ selected.path || selected.key }}
                  </ADescriptionsItem>
                </ADescriptions>
                <div class="ct-actions">
                  <AButton
                    type="primary"
                    :loading="annotateLoading"
                    :disabled="!preview?.raw"
                    @click="doAnnotate"
                  >
                    生成注释
                  </AButton>
                  <ASelect
                    v-model:value="promptType"
                    :options="promptOptions"
                    :disabled="!hasAnnotate"
                    style="width: 160px"
                    placeholder="式样书类型"
                  />
                  <AButton
                    :loading="specLoading"
                    :disabled="!hasAnnotate"
                    @click="doSpec"
                  >
                    生成式样书
                  </AButton>
                </div>
              </div>

              <div v-if="selected.calls?.length" class="mt-sm">
                <span class="sec">CALL</span>
                <ATag v-for="c in selected.calls" :key="c">{{ c }}</ATag>
              </div>
              <div v-if="selected.copies?.length" class="mt-sm">
                <span class="sec">COPY</span>
                <ATag v-for="c in selected.copies" :key="c" color="purple">
                  {{ c }}
                </ATag>
              </div>

              <ATabs v-model:active-key="activeTab" class="mt">
                <ATabPane key="source" tab="源码">
                  <ASpin :spinning="previewLoading">
                    <div v-if="preview?.snippet">
                      <div class="sec">
                        源码
                        <span class="sec-meta">
                          第 {{ preview.start_line }}–{{ preview.end_line }} 行 /
                          共 {{ preview.lines }} 行
                          <template v-if="preview.truncated">（已截断）</template>
                        </span>
                      </div>
                      <pre class="ct-code">{{ preview.snippet }}</pre>
                    </div>
                    <AEmpty v-else description="加载源码中…" />
                  </ASpin>
                </ATabPane>
                <ATabPane key="annotate" tab="注释结果">
                  <template v-if="annotateResult">
                    <AAlert
                      v-if="annotateResult.disclaimer"
                      type="warning"
                      show-icon
                      :message="annotateResult.disclaimer"
                      class="mb"
                    />
                    <div class="ann-actions">
                      <AButton size="small" @click="copyAnnotated">
                        复制注释代码
                      </AButton>
                      <ATag v-if="annotateResult.uncovered" color="orange">
                        含 TODO[KB]
                      </ATag>
                      <ATag v-else color="green">证据覆盖较好</ATag>
                    </div>
                    <pre class="ct-code wrap">{{ annotateResult.annotated_code }}</pre>

                    <div v-if="annotateResult.notes?.length" class="mt">
                      <div class="sec">说明</div>
                      <ul class="ann-notes">
                        <li
                          v-for="(n, i) in annotateResult.notes"
                          :key="i"
                        >
                          {{ n }}
                        </li>
                      </ul>
                    </div>

                    <div v-if="annotateResult.sources?.length" class="mt">
                      <div class="sec">
                        依据来源（{{ annotateResult.sources.length }} 条）
                      </div>
                      <div
                        v-for="s in annotateResult.sources"
                        :key="s.no"
                        class="src-item"
                      >
                        <div class="src-head">
                          <ATag color="blue">[{{ s.no }}]</ATag>
                          <span class="src-path">{{ s.path || s.label }}</span>
                          <ATag v-if="s.type">{{ s.type }}</ATag>
                        </div>
                        <div v-if="s.snippet" class="src-snip">
                          {{ s.snippet }}
                        </div>
                      </div>
                    </div>
                  </template>
                  <AEmpty
                    v-else
                    description="选中代码后点击「生成注释」"
                  />
                </ATabPane>
                <ATabPane key="spec" tab="式样书">
                  <template v-if="specResult">
                    <AAlert
                      v-if="specResult.disclaimer"
                      type="warning"
                      show-icon
                      :message="specResult.disclaimer"
                      class="mb"
                    />
                    <div class="ann-actions">
                      <AButton size="small" @click="copySpec">复制 Markdown</AButton>
                      <AButton
                        size="small"
                        :type="specViewMode === 'render' ? 'primary' : 'default'"
                        @click="specViewMode = 'render'"
                      >
                        渲染
                      </AButton>
                      <AButton
                        size="small"
                        :type="specViewMode === 'raw' ? 'primary' : 'default'"
                        @click="specViewMode = 'raw'"
                      >
                        原文
                      </AButton>
                      <ATag color="blue">{{ specResult.title }}</ATag>
                      <ATag color="processing">注释 + 提示词增强</ATag>
                      <ATag v-if="specResult.uncovered" color="orange">
                        证据不足
                      </ATag>
                    </div>
                    <div v-if="specViewMode === 'render'" class="ds-chat">
                      <div class="ds-bubble">
                        <div class="ds-role">式样书助手</div>
                        <div class="ds-md" v-html="specHtml"></div>
                      </div>
                    </div>
                    <pre v-else class="ct-code wrap">{{ specResult.markdown }}</pre>
                    <div v-if="specResult.notes?.length" class="mt">
                      <div class="sec">说明</div>
                      <ul class="ann-notes">
                        <li v-for="(n, i) in specResult.notes" :key="i">
                          {{ n }}
                        </li>
                      </ul>
                    </div>
                    <div v-if="specResult.sources?.length" class="mt">
                      <div class="sec">
                        依据来源（{{ specResult.sources.length }} 条）
                      </div>
                      <div
                        v-for="s in specResult.sources"
                        :key="s.no"
                        class="src-item"
                      >
                        <div class="src-head">
                          <ATag color="blue">[{{ s.no }}]</ATag>
                          <span class="src-path">{{ s.path || s.label }}</span>
                          <ATag v-if="s.type">{{ s.type }}</ATag>
                        </div>
                        <div v-if="s.snippet" class="src-snip">
                          {{ s.snippet }}
                        </div>
                      </div>
                    </div>
                  </template>
                  <AEmpty
                    v-else
                    description="选择式样书类型后点击「生成式样书」"
                  />
                </ATabPane>
              </ATabs>
            </template>
            <AEmpty v-else description="在左侧选择程序或段" />
          </ACard>
        </ACol>
      </ARow>
    </div>
  </Page>
</template>

<style scoped>
.ct-wrap {
  max-width: 1440px;
  margin: 0 auto;
}
.ct-title {
  font-size: 18px;
  font-weight: 600;
}
.ct-sub {
  margin-top: 4px;
  color: hsl(var(--muted-foreground));
  font-size: 13px;
}
.ct-stats {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 10px;
}
.mb {
  margin-bottom: 12px;
}
.ct-tools {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.ct-tree {
  max-height: 680px;
  overflow: auto;
}
.ct-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.ct-desc {
  flex: 1;
  min-width: 0;
}
.ct-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
  min-width: 160px;
}
.sec {
  font-size: 13px;
  font-weight: 600;
  margin-right: 6px;
  margin-bottom: 6px;
}
.sec-meta {
  margin-left: 8px;
  font-weight: 400;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
.ct-code {
  margin-top: 8px;
  padding: 12px;
  max-height: 560px;
  overflow: auto;
  background: hsl(var(--muted) / 0.35);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre;
}
.ct-code.wrap {
  white-space: pre-wrap;
  word-break: break-all;
}
.ann-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}
.ann-notes {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
.src-item {
  padding: 8px 0;
  border-bottom: 1px solid hsl(var(--border));
}
.src-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.src-path {
  font-size: 13px;
  word-break: break-all;
}
.src-snip {
  margin-top: 4px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  line-height: 1.4;
}

/* DeepSeek 风格对话渲染 */
.ds-chat {
  margin-top: 8px;
}
.ds-bubble {
  padding: 16px 18px;
  border-radius: 12px;
  background: linear-gradient(
    180deg,
    hsl(var(--muted) / 0.45) 0%,
    hsl(var(--muted) / 0.25) 100%
  );
  border: 1px solid hsl(var(--border));
  max-height: 560px;
  overflow: auto;
}
.ds-role {
  font-size: 12px;
  font-weight: 600;
  color: hsl(var(--muted-foreground));
  margin-bottom: 10px;
}
.ds-md {
  font-size: 14px;
  line-height: 1.75;
  color: hsl(var(--foreground));
  word-break: break-word;
}
.ds-md :deep(h1),
.ds-md :deep(h2),
.ds-md :deep(h3),
.ds-md :deep(h4) {
  margin: 1.1em 0 0.45em;
  font-weight: 650;
  line-height: 1.35;
}
.ds-md :deep(h1) {
  font-size: 1.35em;
  padding-bottom: 0.35em;
  border-bottom: 1px solid hsl(var(--border));
}
.ds-md :deep(h2) {
  font-size: 1.18em;
}
.ds-md :deep(h3) {
  font-size: 1.05em;
}
.ds-md :deep(p) {
  margin: 0.55em 0;
}
.ds-md :deep(ul),
.ds-md :deep(ol) {
  margin: 0.45em 0;
  padding-left: 1.4em;
}
.ds-md :deep(li) {
  margin: 0.2em 0;
}
.ds-md :deep(blockquote) {
  margin: 0.7em 0;
  padding: 0.35em 0.9em;
  border-left: 3px solid hsl(212 100% 45% / 0.55);
  color: hsl(var(--muted-foreground));
  background: hsl(var(--background) / 0.45);
  border-radius: 0 6px 6px 0;
}
.ds-md :deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: hsl(var(--background) / 0.7);
}
.ds-md :deep(pre) {
  margin: 0.75em 0;
  padding: 12px 14px;
  overflow: auto;
  border-radius: 8px;
  background: hsl(222 15% 10%);
  color: hsl(0 0% 92%);
  font-size: 12.5px;
  line-height: 1.5;
}
.ds-md :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}
.ds-md :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
  font-size: 13px;
}
.ds-md :deep(th),
.ds-md :deep(td) {
  border: 1px solid hsl(var(--border));
  padding: 6px 10px;
  text-align: left;
}
.ds-md :deep(th) {
  background: hsl(var(--muted) / 0.5);
  font-weight: 600;
}
.ds-md :deep(hr) {
  border: none;
  border-top: 1px solid hsl(var(--border));
  margin: 1em 0;
}
.ds-md :deep(a) {
  color: hsl(212 100% 55%);
}
</style>
