<script lang="ts" setup>
import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Card as ACard,
  Col as ACol,
  Input as AInput,
  List as AList,
  ListItem as AListItem,
  ListItemMeta as AListItemMeta,
  Row as ARow,
  Switch as ASwitch,
  Tag as ATag,
  message,
} from 'ant-design-vue';

import { listPrompts, resetPrompt, updatePrompt } from '#/api/kb';

defineOptions({ name: 'KbPrompts' });

const ATextArea = AInput.TextArea;

const loading = ref(false);
const saving = ref(false);
const items = ref<any[]>([]);
const currentType = ref('program');

const current = computed(
  () => items.value.find((i) => i.type === currentType.value) || null,
);

const draftTitle = ref('');
const draftPrompt = ref('');
const draftEnabled = ref(true);

function syncDraft(row: any | null) {
  draftTitle.value = row?.title || '';
  draftPrompt.value = row?.system_prompt || '';
  draftEnabled.value = row?.enabled !== false;
}

watch(current, (row) => syncDraft(row), { immediate: true });

async function load() {
  loading.value = true;
  try {
    items.value = (await listPrompts()) || [];
    if (!items.value.some((i) => i.type === currentType.value)) {
      currentType.value = items.value[0]?.type || 'program';
    }
    syncDraft(current.value);
  } catch (e: any) {
    message.error(e?.message ?? '加载失败');
  } finally {
    loading.value = false;
  }
}

function selectType(type: string) {
  currentType.value = type;
}

async function save() {
  if (!currentType.value) return;
  if (!draftPrompt.value.trim()) {
    message.warning('提示词不能为空');
    return;
  }
  saving.value = true;
  try {
    const updated = await updatePrompt(currentType.value, {
      title: draftTitle.value.trim(),
      system_prompt: draftPrompt.value,
      enabled: draftEnabled.value,
    });
    const idx = items.value.findIndex((i) => i.type === currentType.value);
    if (idx >= 0) items.value[idx] = updated;
    else items.value.push(updated);
    message.success('已保存');
  } catch (e: any) {
    message.error(e?.message ?? '保存失败（需 gov/admin）');
  } finally {
    saving.value = false;
  }
}

async function doReset() {
  if (!currentType.value) return;
  saving.value = true;
  try {
    const updated = await resetPrompt(currentType.value);
    const idx = items.value.findIndex((i) => i.type === currentType.value);
    if (idx >= 0) items.value[idx] = updated;
    syncDraft(updated);
    message.success('已恢复默认');
  } catch (e: any) {
    message.error(e?.message ?? '恢复失败（需 gov/admin）');
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Page>
    <div class="pm-wrap">
      <ACard :body-style="{ padding: '16px 20px' }">
        <div class="pm-title">式样书提示词配置</div>
        <div class="pm-sub">
          按类型维护 system prompt（程序 / 接口 / 批处理 / COPYBOOK）。本期仅配置，不接生成链路。
        </div>
      </ACard>

      <ARow class="mt" :gutter="16">
        <ACol :span="7">
          <ACard title="类型" :body-style="{ padding: '8px 12px' }">
            <AList :loading="loading" item-layout="horizontal" :data-source="items">
              <template #renderItem="{ item }">
                <AListItem
                  class="pm-item"
                  :class="{ active: item.type === currentType }"
                  @click="selectType(item.type)"
                >
                  <AListItemMeta :title="item.title" :description="item.type" />
                  <template #actions>
                    <ATag :color="item.enabled ? 'green' : 'default'">
                      {{ item.enabled ? '启用' : '停用' }}
                    </ATag>
                  </template>
                </AListItem>
              </template>
            </AList>
          </ACard>
        </ACol>

        <ACol :span="17">
          <ACard title="编辑" :body-style="{ padding: '16px 20px' }">
            <template v-if="current">
              <div class="pm-form">
                <div class="pm-row">
                  <span class="pm-label">标题</span>
                  <AInput v-model:value="draftTitle" style="max-width: 360px" />
                </div>
                <div class="pm-row">
                  <span class="pm-label">启用</span>
                  <ASwitch v-model:checked="draftEnabled" />
                </div>
                <div class="pm-row grow">
                  <span class="pm-label">System Prompt</span>
                  <ATextArea
                    v-model:value="draftPrompt"
                    :rows="18"
                    class="pm-ta"
                    placeholder="式样书 system prompt…"
                  />
                </div>
                <div class="pm-actions">
                  <AButton :loading="loading" @click="load">重新加载</AButton>
                  <AButton :loading="saving" @click="doReset">恢复默认</AButton>
                  <AButton type="primary" :loading="saving" @click="save">
                    保存
                  </AButton>
                </div>
                <div v-if="current.updated_at" class="pm-meta">
                  最近更新：{{ current.updated_by }} ·
                  {{ String(current.updated_at).replace('T', ' ').slice(0, 19) }}
                </div>
              </div>
            </template>
            <div v-else class="pm-empty">暂无配置</div>
          </ACard>
        </ACol>
      </ARow>
    </div>
  </Page>
</template>

<style scoped>
.pm-wrap {
  max-width: 1280px;
  margin: 0 auto;
}
.pm-title {
  font-size: 18px;
  font-weight: 600;
}
.pm-sub {
  margin-top: 4px;
  color: hsl(var(--muted-foreground));
  font-size: 13px;
}
.mt {
  margin-top: 16px;
}
.pm-item {
  cursor: pointer;
  border-radius: 6px;
  padding-inline: 8px;
}
.pm-item.active {
  background: hsl(var(--accent) / 0.35);
}
.pm-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.pm-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pm-row.grow {
  align-items: flex-start;
  flex-direction: column;
}
.pm-label {
  min-width: 110px;
  font-size: 13px;
  font-weight: 600;
}
.pm-ta {
  width: 100%;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.pm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.pm-meta {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  text-align: right;
}
.pm-empty {
  padding: 48px;
  text-align: center;
  color: hsl(var(--muted-foreground));
}
</style>
