<script lang="ts" setup>
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Button as AButton,
  Card as ACard,
  Checkbox as ACheckbox,
  Input as AInput,
  RadioButton as ARadioButton,
  RadioGroup as ARadioGroup,
  Select as ASelect,
  Tag as ATag,
  UploadDragger as AUploadDragger,
  message,
} from 'ant-design-vue';

import { listKmLibraries, uploadKmDoc } from '#/api/kb';

defineOptions({ name: 'KnowledgeUpload' });

const route = useRoute();
const router = useRouter();
const kb = ref((route.query.kb as string) || undefined);
const version = ref<string>('v1.0');
const security = ref('public');
const author = ref('admin');
const tagSearch = ref('');
const selectedTags = ref<string[]>(['SWIFT']);
const official = ref<'official' | 'unofficial'>('official');
const autoChunk = ref(true);
const fileList = ref<any[]>([]);
const uploading = ref(false);
const kbOptions = ref<{ label: string; value: string }[]>([]);

const TAGS = ['SWIFT', 'MT103', 'CNAPS', 'AML', 'Nostro', 'CICS', 'MQ', '对账'];

function toggleTag(tag: string) {
  const i = selectedTags.value.indexOf(tag);
  if (i >= 0) selectedTags.value.splice(i, 1);
  else selectedTags.value.push(tag);
}

const visibleTags = () =>
  TAGS.filter(
    (t) =>
      !tagSearch.value ||
      t.toLowerCase().includes(tagSearch.value.toLowerCase()),
  );

async function onSubmit() {
  if (!version.value) {
    message.warning('请选择版本标签');
    return;
  }
  const files = fileList.value
    .map((f) => f.originFileObj as File)
    .filter(Boolean);
  if (!files.length) {
    message.warning('请先选择文件');
    return;
  }
  uploading.value = true;
  try {
    let ok = 0;
    for (const file of files) {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('library_key', kb.value || 'uploads');
      fd.append('version', version.value);
      fd.append('security', security.value);
      fd.append('author', author.value);
      fd.append('tags', JSON.stringify(selectedTags.value));
      fd.append('official', String(official.value === 'official'));
      fd.append('auto_chunk', String(autoChunk.value));
      await uploadKmDoc(fd);
      ok += 1;
    }
    message.success(`上传成功 ${ok} 个文件`);
    fileList.value = [];
    router.push('/knowledge/docs');
  } catch (e: any) {
    message.error(e?.message || '上传失败');
  } finally {
    uploading.value = false;
  }
}

onMounted(async () => {
  try {
    const libs = await listKmLibraries();
    const opts: { label: string; value: string }[] = [];
    for (const l of libs) {
      opts.push({ label: l.title, value: l.key });
      for (const c of l.children || []) {
        opts.push({ label: `${l.title} / ${c.title}`, value: c.key });
      }
    }
    kbOptions.value = opts;
  } catch {
    kbOptions.value = [];
  }
});
</script>

<template>
  <Page content-class="km-page">
    <div class="km-upload-head">
      <div>
        <h2>上传文档</h2>
        <p class="sub">知识库列表 &gt; 上传文档</p>
      </div>
      <ASelect
        v-model:value="kb"
        allow-clear
        placeholder="全部知识库名称"
        style="width: 280px"
        :options="kbOptions"
      />
    </div>

    <div class="km-upload-grid">
      <ACard title="文件上传" class="km-card">
        <p class="hint">请确保文件编码为 UTF-8 格式，否则上传后会产生乱码</p>
        <AUploadDragger
          v-model:file-list="fileList"
          :multiple="true"
          :before-upload="() => false"
        >
          <p style="font-size: 40px; color: #1677ff; margin: 0">☁</p>
          <p class="ant-upload-text">将文件拖拽到此处</p>
          <AButton type="primary" ghost style="margin-top: 8px">选择文件</AButton>
          <p class="ant-upload-hint">
            单次上传总量 ≤ 5GB；ZIP 内单文件 ≤ 100MB；子目录深度 ≤ 20
          </p>
        </AUploadDragger>
        <div class="formats">
          <div><strong>文档</strong><span>PDF / Word / Markdown / TXT / JSON</span></div>
          <div><strong>代码</strong><span>COBOL / JCL / Python / Java</span></div>
          <div><strong>配置</strong><span>YAML / XML / Shell / MQSC</span></div>
        </div>
      </ACard>

      <ACard title="元数据" class="km-card">
        <p class="hint">元数据将应用于所有上传文件</p>
        <label class="field-label required">版本标签</label>
        <ASelect
          v-model:value="version"
          style="width: 100%; margin-bottom: 14px"
          :options="['v1.0', 'v1.1', 'v2.0', 'v2.1', 'v3.2.1'].map((v) => ({ label: v, value: v }))"
        />
        <label class="field-label">安全等级</label>
        <ASelect
          v-model:value="security"
          style="width: 100%; margin-bottom: 14px"
          :options="[
            { label: '公开', value: 'public' },
            { label: '内部', value: 'internal' },
            { label: '秘密', value: 'secret' },
            { label: '机密', value: 'confidential' },
          ]"
        />
        <label class="field-label">作者</label>
        <AInput v-model:value="author" style="margin-bottom: 14px" />
        <label class="field-label">标签</label>
        <AInput v-model:value="tagSearch" placeholder="搜索标签" style="margin-bottom: 8px" />
        <div class="tag-grid">
          <ATag
            v-for="t in visibleTags()"
            :key="t"
            :color="selectedTags.includes(t) ? 'blue' : 'default'"
            class="tag-chip"
            @click="toggleTag(t)"
          >
            {{ t }}
          </ATag>
        </div>
        <label class="field-label">知识属性</label>
        <ARadioGroup v-model:value="official" button-style="solid" style="width: 100%; margin-bottom: 12px">
          <ARadioButton value="official" style="width: 50%; text-align: center">官方知识</ARadioButton>
          <ARadioButton value="unofficial" style="width: 50%; text-align: center">非官方知识</ARadioButton>
        </ARadioGroup>
        <ACheckbox v-model:checked="autoChunk" style="margin-bottom: 12px">
          解析完成后自动切片
        </ACheckbox>
        <AButton type="primary" block size="large" :loading="uploading" @click="onSubmit">
          开始上传
        </AButton>
      </ACard>
    </div>
  </Page>
</template>

<style scoped>
.km-upload-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.km-upload-head h2 { margin: 0; font-size: 20px; }
.sub { margin: 4px 0 0; color: #8c8c8c; font-size: 13px; }
.km-upload-grid {
  display: grid;
  grid-template-columns: 1.4fr 0.9fr;
  gap: 12px;
}
.hint { color: #8c8c8c; font-size: 12px; margin: 0 0 12px; }
.formats { margin-top: 16px; display: grid; gap: 8px; font-size: 13px; }
.formats strong { display: inline-block; width: 48px; }
.formats span { color: #8c8c8c; }
.field-label { display: block; font-size: 13px; margin-bottom: 6px; }
.field-label.required::before { content: '* '; color: #ff4d4f; }
.tag-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.tag-chip { cursor: pointer; }
@media (max-width: 960px) {
  .km-upload-grid { grid-template-columns: 1fr; }
}
</style>
