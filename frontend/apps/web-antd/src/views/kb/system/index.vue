<script lang="ts" setup>
import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert as AAlert,
  Badge as ABadge,
  Card as ACard,
  Col as ACol,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Row as ARow,
  Statistic as AStatistic,
  Table as ATable,
  Tag as ATag,
} from 'ant-design-vue';

import { getKbStats, getLlmStatus, listTools, listVersions } from '#/api/kb';

defineOptions({ name: 'KbSystem' });

const llm = ref<any>(null);
const stats = ref<any>(null);
const tools = ref<any[]>([]);
const versions = ref<any[]>([]);

const toolColumns = [
  { title: '工具名', dataIndex: 'name', key: 'name' },
  { title: '说明', dataIndex: 'description', key: 'description' },
  { title: '幂等', dataIndex: 'idempotent', key: 'idempotent', width: 70 },
  { title: '超时', dataIndex: 'timeout_ms', key: 'timeout_ms', width: 90 },
];

const versionColumns = [
  { title: '版本', dataIndex: 'version_no', key: 'version_no', width: 200 },
  { title: '变更说明', dataIndex: 'change_note', key: 'change_note' },
  { title: '变更对象', dataIndex: 'changed_objs', key: 'changed_objs', width: 100 },
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
];

onMounted(async () => {
  [llm.value, stats.value, tools.value, versions.value] = await Promise.all([
    getLlmStatus(),
    getKbStats(),
    listTools(),
    listVersions(),
  ]);
});

function fmtTime(t: string) {
  return t?.replace('T', ' ').slice(0, 19);
}
</script>

<template>
  <Page>
    <div class="sys-wrap">
      <ARow :gutter="16">
        <ACol :span="12">
          <Card :body-style="{ padding: '16px 20px' }" title="AI 服务模式">
            <template v-if="llm">
              <ADescriptions :column="1" bordered size="small">
                <ADescriptionsItem label="推理 LLM">
                  <ABadge
                    :status="llm.llm.mode === 'api' ? 'success' : 'warning'"
                    :text="`${llm.llm.mode.toUpperCase()}｜${llm.llm.name}`"
                  />
                </ADescriptionsItem>
                <ADescriptionsItem label="Embedding">
                  <ABadge
                    :status="llm.embedding.mode === 'api' ? 'success' : 'warning'"
                    :text="`${llm.embedding.mode.toUpperCase()}｜${llm.embedding.name}`"
                  />
                </ADescriptionsItem>
                <ADescriptionsItem label="Rerank">
                  <ABadge
                    :status="llm.rerank.mode === 'api' ? 'success' : 'default'"
                    :text="`${llm.rerank.mode.toUpperCase()}｜${llm.rerank.name}`"
                  />
                </ADescriptionsItem>
              </ADescriptions>
              <AAlert
                v-if="llm.hint"
                class="mt"
                :message="llm.hint"
                type="warning"
                show-icon
              />
            </template>
          </Card>
        </ACol>
        <ACol :span="12">
          <Card
            :body-style="{ padding: '16px 20px' }"
            title="知识存储统计（图谱 / 向量）"
          >
            <template v-if="stats">
              <ARow :gutter="12">
                <ACol :span="8">
                  <AStatistic
                    :value="stats.graph.nodes"
                    title="图谱节点"
                  />
                </ACol>
                <ACol :span="8">
                  <AStatistic
                    :value="stats.graph.edges"
                    title="图谱关系"
                  />
                </ACol>
                <ACol :span="8">
                  <AStatistic
                    :value="Object.values(stats.vector).reduce((a: any, b: any) => a + b, 0)"
                    title="向量 Chunk"
                  />
                </ACol>
              </ARow>
              <div class="tag-cloud mt">
                <template v-for="(v, k) in stats.graph.by_label" :key="k">
                  <ATag v-if="v > 0" color="cyan">{{ k }} × {{ v }}</ATag>
                </template>
              </div>
              <div class="tag-cloud mt">
                <template v-for="(v, k) in stats.vector" :key="k">
                  <ATag color="geekblue">{{ k }} × {{ v }}</ATag>
                </template>
              </div>
            </template>
          </Card>
        </ACol>
      </ARow>

      <Card
        class="mt"
        :body-style="{ padding: '12px' }"
        title="工具接口层（Agent 动态编排预留，统一注册中心）"
      >
        <ATable
          :columns="toolColumns"
          :data-source="tools"
          :pagination="false"
          row-key="name"
          size="small"
        />
      </Card>

      <Card class="mt" :body-style="{ padding: '12px' }" title="知识版本">
        <ATable
          :columns="versionColumns"
          :data-source="versions"
          :pagination="{ pageSize: 8 }"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">
              {{ fmtTime(record.created_at) }}
            </template>
          </template>
        </ATable>
      </Card>
    </div>
  </Page>
</template>

<style lang="scss" scoped>
.sys-wrap {
  display: flex;
  flex-direction: column;
}

.mt {
  margin-top: 12px;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
