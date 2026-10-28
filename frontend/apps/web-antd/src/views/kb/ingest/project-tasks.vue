<script lang="ts" setup>
import type { ProjectJob } from '#/api/code-projects';
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Button, Card, Table, Tag, message } from 'ant-design-vue';
import { listCodeProjects } from '#/api/code-projects';
const router = useRouter();
const jobs = ref<ProjectJob[]>([]);
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const labels: Record<string, string> = { queued: '排队中', running: '解析中', done: '已完成', failed: '失败' };
const columns = [
  { title: '工程', dataIndex: 'project', key: 'project' },
  { title: '版本', dataIndex: 'version', key: 'version' },
  { title: '知识库', dataIndex: 'library', key: 'library' },
  { title: '状态', key: 'status' },
  { title: '操作', key: 'action' },
];
async function load() {
  clearTimeout(timer);
  try { jobs.value = await listCodeProjects(); }
  catch (e: any) { message.error(e?.message || '读取工程任务失败'); }
  if (!disposed) timer = setTimeout(load, 5000);
}
onMounted(load);
onBeforeUnmount(() => { disposed = true; clearTimeout(timer); });
</script>
<template>
  <Card title="代码工程接入任务" style="margin-bottom: 16px">
    <template #extra><Button type="primary" @click="router.push('/knowledge/upload?mode=project')">上传代码工程</Button></template>
    <Table :columns="columns" :data-source="jobs" row-key="job_id" :pagination="{ pageSize: 8 }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <Tag :color="record.status === 'failed' ? 'red' : record.status === 'done' ? 'green' : 'blue'">{{ labels[record.status] || record.status }}</Tag>
          <Tag v-if="record.superseded_by">已被重新上传替换</Tag>
        </template>
        <Button v-else-if="column.key === 'action'" type="link" @click="router.push(`/kb/code-projects/${record.job_id}`)">查看进度与结果</Button>
      </template>
    </Table>
  </Card>
</template>
