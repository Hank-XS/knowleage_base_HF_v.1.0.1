<script lang="ts" setup>
import type { KbAnswerPayload, KbSource, KbSourcePreview, QaSessionSummary } from '#/api/kb';
import { computed, nextTick, onMounted, ref } from 'vue';
import { Page } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';
import { Alert, Button, Card, Empty, Input, InputSearch, Modal, Spin, Switch, Tag, message } from 'ant-design-vue';
import { ask, askAgent, createSession, getQaHistory, getQaRuntime, listQaSessions, previewSource, reviewAnswer } from '#/api/kb';

defineOptions({ name: 'KbQa' });
interface ChatItem { role: 'user' | 'assistant'; question: string; answer?: KbAnswerPayload; error?: string }
const userStore = useUserStore();
const canReview = computed(() => ['biz', 'gov', 'admin', 'arch'].includes(userStore.userInfo?.roles?.[0] || ''));
const sessionId = ref(''); const question = ref(''); const loading = ref(false); const opening = ref(true);
const chat = ref<ChatItem[]>([]); const listRef = ref<HTMLElement>(); const agentMode = ref(true);
const sessions = ref<QaSessionSummary[]>([]); const historySearch = ref(''); const historyPage = ref(1); const historyTotal = ref(0); const historyLoading = ref(false);
const runtime = ref<Awaited<ReturnType<typeof getQaRuntime>>>();
const detailsOpen = ref(false); const selectedAnswer = ref<KbAnswerPayload>(); const reviewLoading = ref(false);
const docOpen = ref(false); const docLoading = ref(false); const docPreview = ref<KbSourcePreview | null>(null); const activeSource = ref<KbSource>();
const sourceNames: Record<string, string> = { code: '代码', doc: '文档', graph: '图谱', mapping: '映射' };
const detailSections = [{ key: 'what', label: '结论说明' }, { key: 'why', label: '原因说明' }, { key: 'how', label: '处理建议' }] as const;
let historySequence = 0;

async function loadSessions() {
  const sequence = ++historySequence; historyLoading.value = true;
  try {
    const data = await listQaSessions({ keyword: historySearch.value, page: historyPage.value });
    if (sequence === historySequence) { sessions.value = data.items; historyTotal.value = data.total; }
  } finally { if (sequence === historySequence) historyLoading.value = false; }
}
async function searchHistory() { historyPage.value = 1; await loadSessions(); }
async function changePage(delta: number) { historyPage.value += delta; await loadSessions(); }
function newChat() { if (loading.value || opening.value) return; sessionId.value = ''; chat.value = []; question.value = ''; }
async function openSession(id: string) {
  if (loading.value || opening.value) return;
  opening.value = true;
  try {
    const items = await getQaHistory(id);
    sessionId.value = id; question.value = '';
    chat.value = items.flatMap(item => [{ role: 'user' as const, question: item.question }, { role: 'assistant' as const, question: item.question, answer: item }]);
    await scrollBottom(false);
  } catch { message.error('会话加载失败，请稍后重试'); }
  finally { opening.value = false; }
}
onMounted(async () => {
  try { await loadSessions(); opening.value = false; if (sessions.value[0]) await openSession(sessions.value[0].session_id); }
  catch { message.error('历史记录加载失败，可稍后刷新重试'); }
  finally { opening.value = false; }
  try { runtime.value = await getQaRuntime(); } catch { /* Status does not block asking. */ }
});
async function scrollBottom(smooth = true) { await nextTick(); listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: smooth ? 'smooth' : 'instant' }); }
async function send() {
  const text = question.value.trim(); if (!text || loading.value || opening.value) return;
  loading.value = true; question.value = '';
  chat.value.push({ role: 'user', question: text }); await scrollBottom();
  try {
    if (!sessionId.value) sessionId.value = (await createSession()).session_id;
    const answer = agentMode.value ? await askAgent(sessionId.value, text) : await ask(sessionId.value, text);
    chat.value.push({ role: 'assistant', question: text, answer });
    try { await loadSessions(); } catch { message.warning('答案已保存，历史列表暂未刷新'); }
  } catch (error: any) {
    chat.value.push({ role: 'assistant', question: text, error: error?.message || '本次回答未完成，请重试。' }); question.value = text;
  } finally { loading.value = false; await scrollBottom(); }
}
function onEnter(event: KeyboardEvent) { if (event.isComposing) return; event.preventDefault(); void send(); }
function summary(answer: KbAnswerPayload) { return answer.answer.summary || answer.answer.what || answer.answer.how || answer.answer.why || '暂时无法确认，请补充问题中的工程或文件名称。'; }
function openDetails(answer: KbAnswerPayload) { selectedAnswer.value = answer; detailsOpen.value = true; }
function timeLabel(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }); }
async function doReview(verdict: 'approved' | 'rejected') {
  const answer = selectedAnswer.value; if (!answer) return; reviewLoading.value = true;
  try { await reviewAnswer(answer.answer_id, verdict); answer.review_status = verdict === 'approved' ? 'verified' : 'rejected'; message.success(verdict === 'approved' ? '已复核并保存为可复用答案' : '已驳回'); }
  finally { reviewLoading.value = false; }
}
async function openSource(source: KbSource) {
  activeSource.value = source; docOpen.value = true; docLoading.value = true; docPreview.value = null;
  try { docPreview.value = await previewSource({ ...source, answer_id: selectedAnswer.value?.answer_id, path: source.path || source.obj || source.label }); }
  catch { docPreview.value = { available: !!source.snippet, content: source.snippet || '暂时无法加载原文', from_cache: true, loc: source.loc, path: source.path || source.obj || '', snippet: source.snippet, title: source.ref, type: source.type }; }
  finally { docLoading.value = false; }
}
function escapeHtml(text: string) { return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'); }
function highlightedContent(content: string, snippet?: string) {
  const part = (snippet || '').trim().slice(0, 80);
  return part && content.includes(part) ? content.split(part).map(escapeHtml).join(`<mark>${escapeHtml(part)}</mark>`) : escapeHtml(content);
}
</script>

<template>
  <Page>
    <div class="qa-wrap">
      <div class="qa-header"><div><h1>问答控制台</h1><p>基于已入库资料回答，支持在同一会话中继续追问。</p></div>
        <details class="settings"><summary>问答设置</summary><div><Switch v-model:checked="agentMode" size="small" :disabled="loading" /> 自动选择检索工具</div></details>
      </div>
      <Alert v-if="runtime?.llm.mode === 'mock'" class="runtime-note" type="info" show-icon message="当前为演示模式：展示检索片段，尚未启用模型综合回答。" />
      <div class="qa-main">
        <Card class="history-panel" :body-style="{ padding: '16px', height: '100%' }">
          <div class="history-heading"><strong>问答历史</strong><Button :disabled="loading || opening" size="small" type="primary" @click="newChat">新对话</Button></div>
          <InputSearch v-model:value="historySearch" allow-clear placeholder="搜索历史问题" @search="searchHistory" />
          <Spin :spinning="historyLoading" class="history-content"><nav aria-label="历史会话">
            <button v-for="session in sessions" :key="session.session_id" type="button" class="history-item" :class="{ active: sessionId === session.session_id }" :disabled="loading || opening" @click="openSession(session.session_id)">
              <strong :title="session.title">{{ session.title }}</strong><span>{{ timeLabel(session.updated_at) }} · {{ session.message_count }} 轮问答</span>
            </button><Empty v-if="!sessions.length && !historyLoading" :description="historySearch ? '没有匹配的历史问题' : '开始提问后，会话会自动保存'" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
          </nav></Spin>
          <div v-if="historyTotal > 20" class="history-pages"><Button size="small" :disabled="historyPage === 1 || historyLoading" @click="changePage(-1)">上一页</Button><span>{{ historyPage }} / {{ Math.ceil(historyTotal / 20) }}</span><Button size="small" :disabled="historyPage * 20 >= historyTotal || historyLoading" @click="changePage(1)">下一页</Button></div>
        </Card>
        <Card class="qa-chat" :body-style="{ padding: '20px', height: '100%' }">
          <div class="conversation-heading"><strong>{{ sessionId ? '当前会话' : '新对话' }}</strong><span>历史会话可直接打开并继续提问</span></div>
          <div ref="listRef" class="chat-list" :aria-busy="loading || opening">
            <Spin v-if="opening" class="opening" />
            <Empty v-else-if="!chat.length" class="chat-empty" description="输入问题开始对话。写明工程、程序或文档名称，有助于定位相关资料。" />
            <div v-for="(item, index) in chat" :key="index" class="row" :class="item.role">
              <div v-if="item.role === 'user'" class="bubble user-bubble">{{ item.question }}</div>
              <div v-else class="bubble answer-bubble">
                <template v-if="item.answer">
                  <p class="answer-text">{{ summary(item.answer) }}</p>
                  <p v-if="runtime?.llm.mode !== 'mock' && item.answer.answer.caveats?.length" class="answer-caveat">注意：{{ item.answer.answer.caveats.join('；') }}</p>
                  <div class="answer-footer"><Button type="link" size="small" @click="openDetails(item.answer)">补充说明与依据<template v-if="item.answer.sources?.length">（{{ item.answer.sources.length }}）</template></Button><span v-if="item.answer.review_status === 'verified'">已复核</span></div>
                </template><p v-else class="error-text">{{ item.error }}</p>
              </div>
            </div>
            <div v-if="loading" class="row assistant"><div class="loading-bubble"><Spin size="small" /><span>正在查找资料并整理回答…</span></div></div>
          </div>
          <div class="chat-input"><Input.TextArea v-model:value="question" :auto-size="{ minRows: 2, maxRows: 5 }" :disabled="loading || opening" placeholder="请输入问题（Enter 发送，Shift + Enter 换行）" @keydown.enter.exact="onEnter" /><Button type="primary" :loading="loading" :disabled="opening || !question.trim()" @click="send">发送</Button></div>
        </Card>
      </div>
    </div>
    <Modal v-model:open="detailsOpen" title="补充说明与依据" :footer="null" width="800px">
      <div v-if="selectedAnswer" class="answer-details">
        <section v-for="section in detailSections" :key="section.key"><template v-if="selectedAnswer.answer[section.key]"><h3>{{ section.label }}</h3><p>{{ selectedAnswer.answer[section.key] }}</p></template></section>
        <section v-if="selectedAnswer.answer.caveats?.length"><h3>使用说明</h3><p>{{ selectedAnswer.answer.caveats.join('；') }}</p></section>
        <section><h3>依据来源</h3><p v-if="!selectedAnswer.sources?.length">本次没有可查看的依据来源。</p><button v-for="source in selectedAnswer.sources" :key="source.no" type="button" class="source-link" @click="openSource(source)"><Tag>{{ sourceNames[source.type] || source.type }}</Tag><span>[{{ source.no }}] {{ source.ref || source.label }}<small>{{ source.loc }}</small></span><span>查看原文 →</span></button></section>
        <div v-if="canReview && selectedAnswer.review_status === 'pending_review'" class="review-actions"><Button type="primary" :loading="reviewLoading" @click="doReview('approved')">复核通过并保存</Button><Button danger :loading="reviewLoading" @click="doReview('rejected')">驳回</Button></div>
      </div>
    </Modal>
    <Modal v-model:open="docOpen" :title="docPreview?.title || activeSource?.ref || '依据原文'" :footer="null" width="860px" destroy-on-close>
      <p class="doc-path">{{ docPreview?.path }} {{ docPreview?.loc }}</p><Tag v-if="docPreview?.from_cache">当前显示检索片段</Tag>
      <Spin :spinning="docLoading"><div v-if="docPreview?.content" class="doc-body" v-html="highlightedContent(docPreview.content, docPreview.snippet || activeSource?.snippet)"></div><Empty v-else description="暂无原文" /></Spin>
    </Modal>
  </Page>
</template>

<style scoped>
.qa-wrap{display:flex;flex-direction:column;gap:14px;height:calc(100vh - 145px);min-height:520px}.qa-header{display:flex;align-items:center;justify-content:space-between;gap:20px}.qa-header h1{font-size:23px;font-weight:600}.qa-header p,.conversation-heading>span{font-size:13px;color:hsl(var(--muted-foreground));margin-top:5px}.settings{position:relative;font-size:12px;flex-shrink:0}.settings summary{cursor:pointer}.settings>div{position:absolute;right:0;top:28px;z-index:5;width:220px;padding:16px;background:hsl(var(--card));border:1px solid hsl(var(--border));border-radius:8px}.qa-main{display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;flex:1;min-height:0}.history-panel,.qa-chat{min-height:0}.history-panel :deep(.ant-card-body),.qa-chat :deep(.ant-card-body){display:flex;flex-direction:column;min-height:0}.history-heading,.conversation-heading{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:16px}.history-content{flex:1;min-height:0;overflow:auto;margin-top:12px}.history-content :deep(.ant-spin-container){height:100%}.history-item{display:flex;flex-direction:column;gap:8px;width:100%;padding:14px 12px;margin-bottom:6px;border:1px solid transparent;border-radius:8px;text-align:left;cursor:pointer;background:transparent;color:inherit}.history-item strong{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:100%;font-size:13px;font-weight:500}.history-item span{font-size:11px;color:hsl(var(--muted-foreground))}.history-item.active,.history-item:hover{background:hsl(var(--primary)/.08);border-color:hsl(var(--primary)/.35)}.history-item:disabled{cursor:wait}.history-pages{display:flex;justify-content:space-between;align-items:center;gap:6px;padding-top:12px;font-size:12px}.chat-list{flex:1;min-height:0;overflow:auto;padding:12px 4px}.chat-empty{margin:70px 30px}.opening{display:block;margin:50px auto}.row{display:flex;margin-bottom:22px}.row.user{justify-content:flex-end}.bubble{max-width:88%;padding:14px 18px;border-radius:12px;overflow-wrap:anywhere;white-space:pre-wrap}.user-bubble{background:hsl(var(--primary));color:#fff}.answer-bubble{background:hsl(var(--muted)/.4);min-width:220px}.answer-text{font-size:14px;line-height:1.85;margin:0}.answer-caveat{font-size:12px;color:hsl(var(--muted-foreground));margin:12px 0 0}.answer-footer{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:12px;color:hsl(var(--muted-foreground));font-size:11px}.answer-footer :deep(.ant-btn){padding-left:0}.loading-bubble{display:flex;align-items:center;gap:12px;color:hsl(var(--muted-foreground));font-size:13px}.chat-input{display:flex;align-items:flex-end;gap:12px;border-top:1px solid hsl(var(--border));padding-top:16px}.chat-input :deep(textarea){resize:none}.chat-input>.ant-btn{height:42px;flex-shrink:0}.answer-details{max-height:66vh;overflow:auto;padding-right:8px}.answer-details section{margin-bottom:22px}.answer-details h3{font-size:14px;font-weight:600;margin-bottom:8px}.answer-details p{white-space:pre-wrap;line-height:1.8;overflow-wrap:anywhere}.source-link{display:flex;gap:10px;align-items:center;width:100%;padding:12px 0;border-bottom:1px solid hsl(var(--border));text-align:left;cursor:pointer}.source-link>span:nth-child(2){flex:1;overflow-wrap:anywhere}.source-link small{display:block;color:hsl(var(--muted-foreground))}.source-link>span:last-child{font-size:12px;color:hsl(var(--primary));flex-shrink:0}.review-actions{display:flex;gap:10px}.doc-path{overflow-wrap:anywhere;font-size:12px;color:hsl(var(--muted-foreground))}.doc-body{white-space:pre-wrap;overflow:auto;max-height:60vh;background:hsl(var(--muted)/.5);padding:16px;font-family:monospace;font-size:12px;line-height:1.75}.doc-body :deep(mark){background:#ffe58f}.error-text{color:#dc2626}
@media(max-width:1050px){.qa-main{grid-template-columns:220px minmax(0,1fr)}.conversation-heading>span{display:none}}@media(max-width:760px){.qa-wrap{height:auto;min-height:calc(100vh - 145px)}.qa-main{grid-template-columns:1fr}.history-panel{max-height:250px}.qa-chat{height:65vh}.bubble{max-width:96%}.source-link{flex-wrap:wrap}.settings{display:none}}
</style>
