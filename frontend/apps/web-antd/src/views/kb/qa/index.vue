<script lang="ts" setup>
import type { KbAnswerPayload, KbSource, KbSourcePreview } from '#/api/kb';
import type { UserInfo } from '@vben/types';

import { computed, nextTick, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import {
  Alert as AAlert,
  Badge as ABadge,
  Button as AButton,
  Card as ACard,
  Collapse as ACollapse,
  CollapsePanel as ACollapsePanel,
  Empty as AEmpty,
  Input as AInput,
  Modal as AModal,
  Switch as ASwitch,
  Spin as ASpin,
  Tag as ATag,
  Tooltip as ATooltip,
  message,
} from 'ant-design-vue';

import {
  ask,
  askAgent,
  createSession,
  previewSource,
  reviewAnswer,
} from '#/api/kb';

defineOptions({ name: 'KbQa' });

interface ChatItem {
  answer?: KbAnswerPayload;
  question: string;
  role: 'assistant' | 'user';
}

const userStore = useUserStore();
const userInfo = computed<UserInfo>(() => userStore.userInfo);
const role = computed(() => userInfo.value?.roles?.[0] ?? '');
const canReview = computed(() =>
  ['biz', 'gov', 'admin', 'arch'].includes(role.value),
);

const sessionId = ref('');
const question = ref('');
const loading = ref(false);
const chat = ref<ChatItem[]>([]);
const listRef = ref<HTMLElement>();
const reviewLoading = ref('');
/** Agent 模式：自动调度文档/代码/图谱等工具 */
const agentMode = ref(true);

const docOpen = ref(false);
const docLoading = ref(false);
const docPreview = ref<KbSourcePreview | null>(null);
const activeSource = ref<KbSource | null>(null);

const HIT_TEXT: Record<string, string> = {
  exact: '精确命中 · 直出已验证答案',
  miss: '未命中 · 实时推理',
  similar: '相似命中 · 参考复用',
};
const HIT_COLOR: Record<string, string> = {
  exact: 'green',
  miss: 'blue',
  similar: 'orange',
};
const SRC_COLOR: Record<string, string> = {
  code: 'purple',
  doc: 'geekblue',
  graph: 'cyan',
  mapping: 'gold',
};
const SRC_TEXT: Record<string, string> = {
  code: '代码',
  doc: '文档',
  graph: '图谱',
  mapping: '映射',
};

const suggestions = [
  'ATM取款返回错误码14余额不足，应如何排查处理？',
  '错误码14是什么意思？',
  'Smart卡在系统里属于什么卡种口径？',
  '修改ATMWD402程序会影响哪些接口和子系统？',
];

const lastEntities = computed<string[]>(() => {
  for (let i = chat.value.length - 1; i >= 0; i--) {
    const item = chat.value[i]!;
    if (item.role === 'assistant' && item.answer) {
      return item.answer.entities ?? [];
    }
  }
  return [];
});

onMounted(async () => {
  const s = await createSession();
  sessionId.value = s.session_id;
});

async function scrollBottom() {
  await nextTick();
  listRef.value?.scrollTo({ behavior: 'smooth', top: 1_000_000 });
}

async function send(q?: string) {
  const text = (q ?? question.value).trim();
  if (!text || loading.value || !sessionId.value) return;
  question.value = '';
  chat.value.push({ question: text, role: 'user' });
  loading.value = true;
  await scrollBottom();
  try {
    const payload = agentMode.value
      ? await askAgent(sessionId.value, text)
      : await ask(sessionId.value, text);
    chat.value.push({ answer: payload, question: text, role: 'assistant' });
  } catch (e: any) {
    message.error(e?.message ?? '问答失败');
  } finally {
    loading.value = false;
    await scrollBottom();
  }
}

async function doReview(answerId: string, verdict: 'approved' | 'rejected') {
  reviewLoading.value = answerId + verdict;
  try {
    await reviewAnswer(answerId, verdict);
    const item = chat.value.find(
      (c) => c.answer?.answer_id === answerId,
    )?.answer;
    if (item) {
      item.review_status = verdict === 'approved' ? 'verified' : 'rejected';
    }
    message.success(
      verdict === 'approved'
        ? '已复核通过并沉淀入已验证答案库'
        : '已驳回（不入库）',
    );
  } catch (e: any) {
    message.error(e?.message ?? '复核失败');
  } finally {
    reviewLoading.value = '';
  }
}

async function openSource(s: KbSource, answerId?: string) {
  activeSource.value = s;
  docOpen.value = true;
  docLoading.value = true;
  docPreview.value = null;
  try {
    docPreview.value = await previewSource({
      answer_id: answerId,
      label: s.label,
      loc: s.loc,
      no: s.no,
      obj: s.obj,
      path: s.path || s.obj || s.label,
      ref: s.ref,
      snippet: s.snippet,
      type: s.type,
    });
  } catch (e: any) {
    // 降级：接口失败时仍用片段展示
    docPreview.value = {
      available: Boolean(s.snippet),
      content: s.snippet || e?.message || '无法加载文档',
      from_cache: true,
      loc: s.loc,
      path: s.path || s.obj || s.label || '',
      snippet: s.snippet,
      title: s.ref || s.label || `依据 [${s.no}]`,
      type: s.type,
    };
    if (!s.snippet) message.error(e?.message ?? '加载依据文档失败');
  } finally {
    docLoading.value = false;
  }
}

function closeDoc() {
  docOpen.value = false;
}

/** 将 snippet 在正文中高亮 */
function highlightedContent(content: string, snippet?: string) {
  if (!content) return '';
  const snip = (snippet || '').trim().slice(0, 80);
  if (!snip || !content.includes(snip)) {
    return escapeHtml(content);
  }
  const parts = content.split(snip);
  return parts
    .map((p) => escapeHtml(p))
    .join(`<mark class="src-hl">${escapeHtml(snip)}</mark>`);
}

function escapeHtml(s: string) {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}
</script>

<template>
  <Page>
    <div class="qa-wrap">
      <!-- 会话头部 -->
      <Card class="qa-header" :body-style="{ padding: '14px 20px' }">
        <div class="qa-header-inner">
          <div class="qa-title">
            <span class="qa-logo">KB</span>
            <div>
              <div class="qa-name">核心系统迁移知识库 · 问答控制台</div>
              <div class="qa-sub">
                场景 ATM ｜ 单一 Flow：问题分析 → 三级分流 → 多路检索 →
                整体分析 → 带依据作答
              </div>
            </div>
          </div>
          <div class="qa-meta">
            <span class="agent-switch">
              <ASwitch v-model:checked="agentMode" size="small" />
              <span class="agent-label">
                {{ agentMode ? 'Agent 自动调度工具' : '单一 Flow' }}
              </span>
            </span>
            <ATag color="processing">会话 {{ sessionId.slice(0, 8) }}</ATag>
            <ATag :color="canReview ? 'green' : 'default'">
              当前角色：{{ role || '-' }}
            </ATag>
          </div>
        </div>
      </Card>

      <div class="qa-main">
        <!-- 对话区 -->
        <Card class="qa-chat" :body-style="{ padding: '16px', height: '100%' }">
          <div ref="listRef" class="chat-list">
            <AEmpty
              v-if="chat.length === 0"
              class="chat-empty"
              description="向知识库提问，例如错误码含义、业务规则、代码影响面"
            />
            <template v-for="(item, idx) in chat" :key="idx">
              <div v-if="item.role === 'user'" class="row user">
                <div class="bubble user-bubble">{{ item.question }}</div>
              </div>
              <div v-else class="row assistant">
                <div class="bubble answer-bubble">
                  <template v-if="item.answer">
                    <div class="ans-header">
                      <ABadge
                        :status="
                          item.answer.hit_type === 'exact'
                            ? 'success'
                            : item.answer.hit_type === 'similar'
                              ? 'warning'
                              : 'processing'
                        "
                        :text="HIT_TEXT[item.answer.hit_type]"
                      />
                      <ATag v-if="item.answer.similarity" size="small">
                        相似度 {{ item.answer.similarity }}
                      </ATag>
                      <ATag size="small">{{ item.answer.intent }}</ATag>
                      <span class="ans-ms">{{ item.answer.elapsed_ms }} ms</span>
                    </div>

                    <div class="ans-section what">
                      <div class="sec-title">是什么</div>
                      <div class="sec-body">{{ item.answer.answer.what }}</div>
                    </div>
                    <div class="ans-section why">
                      <div class="sec-title">为什么</div>
                      <div class="sec-body pre">{{ item.answer.answer.why }}</div>
                    </div>
                    <div class="ans-section how">
                      <div class="sec-title">怎么处理</div>
                      <div class="sec-body pre">{{ item.answer.answer.how }}</div>
                    </div>

                    <AAlert
                      v-if="item.answer.answer.caveats?.length"
                      class="ans-caveats"
                      type="warning"
                      show-icon
                    >
                      <template #message>
                        需人工复核：
                        {{ item.answer.answer.caveats.join('；') }}
                      </template>
                    </AAlert>

                    <div class="ans-sources">
                      <div class="src-title">
                        依据来源（{{ item.answer.sources.length }} 条，点击查看原文）
                      </div>
                      <div class="src-list">
                        <ATooltip
                          v-for="s in item.answer.sources"
                          :key="s.no"
                          :title="`点击查看：${s.label || s.ref} ${s.loc || ''}`"
                        >
                          <button
                            class="src-chip"
                            type="button"
                            @click="openSource(s, item.answer?.answer_id)"
                          >
                            <ATag :color="SRC_COLOR[s.type] ?? 'default'">
                              [{{ s.no }}] {{ SRC_TEXT[s.type] ?? s.type }}
                            </ATag>
                            <span class="src-ref">{{ s.ref }}</span>
                          </button>
                        </ATooltip>
                      </div>
                    </div>

                    <ACollapse class="ans-trace" :bordered="false">
                      <ACollapsePanel
                        key="trace"
                        header="推理过程（经得起追问）"
                      >
                        <div
                          v-for="t in item.answer.reasoning_trace"
                          :key="t.step"
                          class="trace-row"
                        >
                          <span class="trace-step">#{{ t.step }}</span>
                          <ATag color="blue" size="small">{{ t.tool }}</ATag>
                          <span class="trace-res">{{ t.result }}</span>
                        </div>
                      </ACollapsePanel>
                    </ACollapse>

                    <div
                      v-if="canReview && item.answer.review_status === 'pending_review'"
                      class="ans-review"
                    >
                      <AButton
                        :loading="reviewLoading === item.answer.answer_id + 'approved'"
                        size="small"
                        type="primary"
                        @click="doReview(item.answer.answer_id, 'approved')"
                      >
                        复核通过并沉淀
                      </AButton>
                      <AButton
                        :loading="reviewLoading === item.answer.answer_id + 'rejected'"
                        danger
                        size="small"
                        @click="doReview(item.answer.answer_id, 'rejected')"
                      >
                        驳回
                      </AButton>
                      <span class="review-tip">
                        miss 答案须人工复核后方可入库复用
                      </span>
                    </div>
                    <div v-else class="ans-status">
                      <ATag
                        :color="
                          item.answer.review_status === 'verified'
                            ? 'green'
                            : item.answer.review_status === 'rejected'
                              ? 'red'
                              : 'default'
                        "
                      >
                        复核状态：{{ item.answer.review_status }}
                      </ATag>
                    </div>
                  </template>
                </div>
              </div>
            </template>
            <div v-if="loading" class="row assistant">
              <div class="bubble answer-bubble loading-bubble">
                <ASpin size="small" />
                <span class="loading-text">
                  多路检索与整体分析中（问题分析 → 分流 → 检索 → 生成）…
                </span>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="chat-input">
            <div class="sug-list">
              <span
                v-for="s in suggestions"
                :key="s"
                class="sug-chip"
                @click="send(s)"
              >
                {{ s }}
              </span>
            </div>
            <div class="input-row">
              <AInput
                v-model:value="question"
                :disabled="loading"
                placeholder="输入问题，回车发送（支持追问）"
                size="large"
                @keyup.enter="send()"
              />
              <AButton
                :loading="loading"
                size="large"
                type="primary"
                @click="send()"
              >
                提问
              </AButton>
            </div>
          </div>
        </Card>

        <!-- 侧栏 -->
        <div class="qa-side">
          <Card size="small" title="长时记忆 · 三级分流">
            <div class="side-row">
              <ABadge status="success" text="精确命中（sim ≥ 0.95）：指纹直出" />
            </div>
            <div class="side-row">
              <ABadge
                status="warning"
                text="相似命中（0.80 ~ 0.95）：参考复用"
              />
            </div>
            <div class="side-row">
              <ABadge status="processing" text="未命中（< 0.80）：实时推理" />
            </div>
            <div class="side-note">
              复核通过的答案写入已验证答案库，同题再次提问将精确命中直接返回。
            </div>
          </Card>
          <Card class="mt" size="small" title="本次会话统计">
            <div class="stat-grid">
              <div class="stat">
                <div class="stat-num">{{ chat.length }}</div>
                <div class="stat-label">消息</div>
              </div>
              <div class="stat">
                <div class="stat-num">
                  {{ chat.filter((c) => c.answer?.hit_type === 'exact').length }}
                </div>
                <div class="stat-label">精确命中</div>
              </div>
              <div class="stat">
                <div class="stat-num">
                  {{ chat.filter((c) => c.answer?.sources?.length).length }}
                </div>
                <div class="stat-label">带溯源答案</div>
              </div>
            </div>
          </Card>
          <Card class="mt" size="small" title="识别实体（最近一条）">
            <template v-if="lastEntities.length">
              <ATag v-for="e in lastEntities" :key="e" color="cyan">{{ e }}</ATag>
            </template>
            <span v-else class="side-note">暂无</span>
          </Card>
        </div>
      </div>
    </div>

    <AModal
      v-model:open="docOpen"
      :footer="null"
      :title="docPreview?.title || activeSource?.ref || '依据文档'"
      destroy-on-close
      width="860px"
      wrap-class-name="src-doc-modal"
      @cancel="closeDoc"
    >
      <div class="doc-meta">
        <ATag :color="SRC_COLOR[docPreview?.type || activeSource?.type || ''] ?? 'default'">
          {{ SRC_TEXT[docPreview?.type || activeSource?.type || ''] || docPreview?.type || 'doc' }}
        </ATag>
        <ATag v-if="activeSource?.no" color="processing">#{{ activeSource.no }}</ATag>
        <ATag v-if="docPreview?.from_cache" color="orange">片段拼合</ATag>
        <span v-if="docPreview?.path" class="doc-path" :title="docPreview.path">
          {{ docPreview.path }}
        </span>
        <span v-if="docPreview?.loc" class="doc-loc">定位：{{ docPreview.loc }}</span>
      </div>
      <ASpin :spinning="docLoading">
        <div
          v-if="docPreview?.content"
          class="doc-body"
          v-html="highlightedContent(docPreview.content, docPreview.snippet || activeSource?.snippet)"
        ></div>
        <AEmpty v-else description="暂无文档内容" />
      </ASpin>
    </AModal>
  </Page>
</template>

<style lang="scss" scoped>
.qa-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 130px);
}

.qa-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.qa-title {
  display: flex;
  gap: 12px;
  align-items: center;
}

.qa-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #1a2330, #d4875a);
  border-radius: 10px;
}

.qa-name {
  font-size: 16px;
  font-weight: 600;
}

.qa-sub {
  margin-top: 2px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.qa-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.agent-switch {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  margin-right: 4px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.agent-label {
  white-space: nowrap;
}

.qa-main {
  display: flex;
  flex: 1;
  gap: 12px;
  min-height: 0;
}

.qa-chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;

  :deep(.ant-card-body) {
    display: flex;
    flex-direction: column;
  }
}

.chat-list {
  flex: 1;
  padding-right: 6px;
  overflow-y: auto;
}

.chat-empty {
  margin-top: 80px;
}

.row {
  display: flex;
  margin-bottom: 14px;

  &.user {
    justify-content: flex-end;
  }
}

.bubble {
  max-width: 86%;
  padding: 10px 14px;
  border-radius: 12px;
}

.user-bubble {
  color: #fff;
  background: hsl(var(--primary));
  border-bottom-right-radius: 2px;
}

.answer-bubble {
  width: 100%;
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-bottom-left-radius: 2px;
}

.loading-bubble {
  display: flex;
  gap: 10px;
  align-items: center;

  .loading-text {
    font-size: 13px;
    color: hsl(var(--muted-foreground));
  }
}

.ans-header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;

  .ans-ms {
    margin-left: auto;
    font-size: 12px;
    color: hsl(var(--muted-foreground));
  }
}

.ans-section {
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 8px;

  .sec-title {
    margin-bottom: 4px;
    font-size: 13px;
    font-weight: 600;
  }

  .sec-body {
    font-size: 13px;
    line-height: 1.7;
    word-break: break-word;
    white-space: pre-wrap;
  }

  &.what {
    background: rgb(82 196 26 / 8%);

    .sec-title {
      color: #389e0d;
    }
  }

  &.why {
    background: rgb(22 119 255 / 8%);

    .sec-title {
      color: #1677ff;
    }
  }

  &.how {
    background: rgb(250 140 22 / 10%);

    .sec-title {
      color: #d46b08;
    }
  }
}

.ans-caveats {
  margin-bottom: 8px;
}

.ans-sources {
  margin-bottom: 8px;

  .src-title {
    margin-bottom: 6px;
    font-size: 13px;
    font-weight: 600;
    color: hsl(var(--muted-foreground));
  }

  .src-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .src-chip {
    display: inline-flex;
    gap: 2px;
    align-items: center;
    padding: 2px 8px 2px 2px;
    margin: 0;
    color: inherit;
    cursor: pointer;
    background: hsl(var(--card));
    border: 1px solid hsl(var(--border));
    border-radius: 6px;
    transition:
      border-color 0.15s,
      color 0.15s,
      box-shadow 0.15s;
    appearance: none;

    &:hover {
      color: hsl(var(--primary));
      border-color: hsl(var(--primary));
      box-shadow: 0 0 0 2px rgb(22 119 255 / 12%);
    }
  }

  .src-ref {
    max-width: 280px;
    overflow: hidden;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.doc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.doc-path {
  max-width: 520px;
  overflow: hidden;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-loc {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.doc-body {
  max-height: min(62vh, 640px);
  padding: 12px 14px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
  word-break: break-word;
  white-space: pre-wrap;
  background: hsl(var(--muted) / 0.35);
  border: 1px solid hsl(var(--border));
  border-radius: 8px;

  :deep(.src-hl) {
    padding: 0 2px;
    color: inherit;
    background: rgb(250 173 20 / 45%);
    border-radius: 2px;
  }
}

.trace-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 3px 0;
  font-size: 12px;

  .trace-step {
    width: 28px;
    color: hsl(var(--muted-foreground));
  }

  .trace-res {
    color: hsl(var(--muted-foreground));
  }
}

.ans-review {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;

  .review-tip {
    font-size: 12px;
    color: hsl(var(--muted-foreground));
  }
}

.ans-status {
  margin-top: 8px;
}

.chat-input {
  padding-top: 10px;
  border-top: 1px solid hsl(var(--border));

  .sug-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }

  .sug-chip {
    padding: 3px 10px;
    font-size: 12px;
    cursor: pointer;
    background: hsl(var(--card));
    border: 1px solid hsl(var(--border));
    border-radius: 999px;
    transition: all 0.2s;

    &:hover {
      color: hsl(var(--primary));
      border-color: hsl(var(--primary));
    }
  }

  .input-row {
    display: flex;
    gap: 8px;
  }
}

.qa-side {
  display: flex;
  flex-direction: column;
  width: 280px;
  flex-shrink: 0;

  .mt {
    margin-top: 12px;
  }

  .side-row {
    margin: 6px 0;
  }

  .side-note {
    margin-top: 8px;
    font-size: 12px;
    line-height: 1.6;
    color: hsl(var(--muted-foreground));
  }

  .stat-grid {
    display: flex;
    justify-content: space-around;
  }

  .stat {
    text-align: center;
  }

  .stat-num {
    font-size: 22px;
    font-weight: 700;
    color: hsl(var(--primary));
  }

  .stat-label {
    font-size: 12px;
    color: hsl(var(--muted-foreground));
  }
}
</style>
