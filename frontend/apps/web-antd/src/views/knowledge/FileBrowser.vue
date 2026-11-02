<script setup lang="ts">
import { ref, watch } from 'vue';
import { Button, Card, Empty, InputSearch, Spin, Tag } from 'ant-design-vue';
import type { KmDoc } from '#/api/kb';
const props = defineProps<{ items: KmDoc[]; selected?: string; total: number; page: number; loading: boolean; search?: string }>();
const emit = defineEmits<{ select: [id: string]; search: [text: string]; page: [page: number] }>();
const keyword = ref('');
watch(() => props.search, value => { keyword.value = value || ''; });
function name(doc: KmDoc) { const base = doc.name.split('/').pop() || doc.name; return base.toLowerCase().endsWith('.' + doc.type.toLowerCase()) ? base : `${base}.${doc.type}`; }
</script>
<template>
  <Card class="file-browser" title="文件列表"><template #extra><small>{{ total }} 个</small></template>
    <InputSearch v-model:value="keyword" placeholder="搜索文件名或路径" allow-clear @search="emit('search', keyword)" @change="() => !keyword && emit('search', '')" />
    <Spin :spinning="loading"><div class="file-items"><button v-for="item in items" :key="item.id" class="file-item" :class="{ selected: selected === item.id }" @click="emit('select', item.id)"><div><strong>{{ name(item) }}</strong><Tag>{{ item.type.toUpperCase() }}</Tag></div><small class="path" :title="item.name">{{ item.name }}</small><small>{{ item.project || '系统通用' }} · {{ item.version }}</small></button><Empty v-if="!items.length && !loading" description="当前筛选下没有文件" /></div></Spin>
    <div v-if="total > 30" class="file-pagination"><Button size="small" :disabled="page <= 1" @click="emit('page', page - 1)">上一页</Button><small>{{ page }} / {{ Math.ceil(total / 30) }}</small><Button size="small" :disabled="page * 30 >= total" @click="emit('page', page + 1)">下一页</Button></div>
  </Card>
</template>
<style scoped>
.file-browser{height:fit-content;position:sticky;top:12px}.file-items{max-height:max(260px,calc(100vh - 560px));overflow:auto;margin-top:14px}.file-item{display:block;width:100%;text-align:left;border:1px solid transparent;border-radius:8px;padding:12px;margin-bottom:6px;cursor:pointer;background:transparent;color:inherit}.file-item:hover{background:hsl(var(--muted))}.file-item.selected{border-color:hsl(var(--primary));background:hsl(var(--primary)/.1)}.file-item>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.file-item strong{overflow-wrap:anywhere}.file-item small{display:block;color:hsl(var(--muted-foreground));margin-top:6px;font-size:11px}.file-item .path{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.file-pagination{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:12px}small{color:hsl(var(--muted-foreground))}
</style>
