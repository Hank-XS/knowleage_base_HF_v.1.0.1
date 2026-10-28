<script lang="ts" setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { Alert, Button, Card, Input, Select, UploadDragger, message } from 'ant-design-vue';
import { uploadCodeProject } from '#/api/code-projects';

const props = defineProps<{ library?: string }>();
const router = useRouter();
const project = ref('');
const version = ref('v1.0');
const encoding = ref('utf-8');
const files = ref<any[]>([]);
const submitting = ref(false);
async function submit() {
  const file = files.value[0]?.originFileObj;
  if (!project.value.trim() || !version.value.trim() || !file) {
    message.warning('请填写工程名称、版本并选择 ZIP');
    return;
  }
  if (!file.name.toLowerCase().endsWith('.zip') || file.size > 50 * 1024 * 1024) {
    message.error('请选择不超过 50 MB 的 ZIP 文件');
    return;
  }
  submitting.value = true;
  try {
    const data = new FormData();
    data.append('file', file);
    data.append('project', project.value.trim());
    data.append('version', version.value.trim());
    data.append('library', props.library || 'code-projects');
    data.append('encoding', encoding.value);
    const job = await uploadCodeProject(data);
    message.success('工程已上传，后台解析任务已创建');
    await router.push(`/kb/code-projects/${job.job_id}`);
  } catch (error: any) {
    message.error(error?.message || '工程上传失败');
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Card title="上传完整 COBOL 工程">
    <Alert type="info" show-icon message="本地解析，无需配置大模型"
      description="将主程序、被调用程序和 Copybook 一起打包，保留目录。解析后可查看源码、结构切片、调用关系和缺失依赖。" />
    <div class="fields">
      <label>工程名称<Input v-model:value="project" :maxlength="100" placeholder="例如：账户核心系统" /></label>
      <label>工程版本<Input v-model:value="version" :maxlength="32" placeholder="例如：v1.0" /></label>
      <label>源码编码<Select v-model:value="encoding" style="width: 100%" :options="[{ label: 'UTF-8', value: 'utf-8' }, { label: 'GB18030 / GBK', value: 'gb18030' }]" /></label>
    </div>
    <UploadDragger v-model:file-list="files" accept=".zip" :max-count="1" :before-upload="() => false">
      <p class="ant-upload-text">拖入工程 ZIP，或点击选择文件</p>
      <p class="ant-upload-hint">ZIP ≤ 50 MB，解压后 ≤ 200 MB，最多 5000 个条目，单个源码 ≤ 1 MB</p>
      <p class="ant-upload-hint">解析 .cbl / .cob / .cobol / .cpy；其他文件会列入跳过报告。</p>
    </UploadDragger>
    <p class="note">同一知识库、工程名称和版本重新上传时，解析成功后替换该版本的索引；失败会保留之前的结果。不同版本独立保存。</p>
    <Button type="primary" :loading="submitting" @click="submit">上传并解析工程</Button>
  </Card>
</template>

<style scoped>
.fields { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 18px; margin: 24px 0; }
.fields label { display: flex; flex-direction: column; gap: 8px; }
.note { margin: 18px 0; color: hsl(var(--muted-foreground)); }
@media (max-width: 800px) { .fields { grid-template-columns: 1fr; } }
</style>
