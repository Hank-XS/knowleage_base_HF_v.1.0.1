<script lang="ts" setup>
import { ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Col as ACol,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Input as AInput,
  RadioButton as ARadioButton,
  RadioGroup as ARadioGroup,
  Row as ARow,
  Statistic as AStatistic,
  TabPane as ATabPane,
  Tabs as ATabs,
  Tag as ATag,
  message,
} from 'ant-design-vue';

import { analyzeImpact, generateSkeleton } from '#/api/kb';

defineOptions({ name: 'KbImpact' });

// ---------------- 影响分析 ----------------
const impactTarget = ref('ATMWD402');
const changeSummary = ref('');
const impactLoading = ref(false);
const impact = ref<any>(null);

async function doImpact() {
  const name = impactTarget.value.trim();
  if (!name) {
    message.warning('请填写目标对象');
    return;
  }
  impactLoading.value = true;
  try {
    impact.value = await analyzeImpact(name, changeSummary.value.trim());
    if (!impact.value?.found) {
      message.warning(impact.value?.message ?? '图谱中未找到该对象');
    }
  } catch (e: any) {
    message.error(e?.message ?? '分析失败');
  } finally {
    impactLoading.value = false;
  }
}

// ---------------- 代码骨架 ----------------
const ifaceId = ref('ATM取款接口');
const codeTarget = ref<'python_script' | 'spring_controller'>(
  'spring_controller',
);
const codeLoading = ref(false);
const codegen = ref<any>(null);

async function doCodegen() {
  const iface = ifaceId.value.trim();
  if (!iface) {
    message.warning('请填写接口名');
    return;
  }
  const lang =
    codeTarget.value === 'python_script'
      ? 'python_script'
      : 'spring_controller';
  codeLoading.value = true;
  try {
    codegen.value = await generateSkeleton(iface, lang);
  } catch (e: any) {
    message.error(e?.message ?? '生成失败');
  } finally {
    codeLoading.value = false;
  }
}

function riskColor(r: string) {
  return r === 'high' ? 'red' : r === 'medium' ? 'orange' : 'green';
}
</script>

<template>
  <Page>
    <div class="imp-wrap">
      <ACard :body-style="{ padding: '16px 20px' }">
        <div class="imp-title">迁移支撑 · 影响分析与代码骨架生成</div>
        <div class="imp-sub">
          修改老代码前评估波及面（图谱 3 跳影响面 + 耦合度）；依据接口定义与
          mapping 生成新系统代码骨架
        </div>
      </ACard>

      <ACard class="mt" :body-style="{ padding: '16px 20px' }" title="影响分析">
        <div class="imp-form">
          <AInput
            v-model:value="impactTarget"
            placeholder="目标对象（如 ATMWD402 / ATM取款接口）"
            style="width: 280px"
          />
          <AInput
            v-model:value="changeSummary"
            placeholder="变更说明（可选）"
            style="width: 320px"
          />
          <AButton :loading="impactLoading" type="primary" @click="doImpact">
            分析影响面
          </AButton>
        </div>

        <template v-if="impact?.found">
          <ARow class="mt" :gutter="16">
            <ACol :span="6">
              <ACard size="small">
                <AStatistic
                  :value="impact.affected.total"
                  title="波及对象总数"
                />
              </ACard>
            </ACol>
            <ACol :span="6">
              <ACard size="small">
                <AStatistic
                  :value="impact.affected.interfaces"
                  title="受影响接口"
                />
              </ACard>
            </ACol>
            <ACol :span="6">
              <ACard size="small">
                <AStatistic
                  :value="impact.affected.subsystems"
                  title="受影响子系统"
                />
              </ACard>
            </ACol>
            <ACol :span="6">
              <ACard size="small">
                <div class="risk-cell">
                  <ATag :color="riskColor(impact.risk_level)" class="risk-tag">
                    {{ impact.risk_level }}
                  </ATag>
                  <span class="risk-label">风险等级</span>
                </div>
                <div class="coupling">
                  耦合度 {{ impact.metrics.coupling_score }}
                </div>
              </ACard>
            </ACol>
          </ARow>

          <ADescriptions
            class="mt"
            :column="3"
            bordered
            size="small"
            title="分层数量"
          >
            <ADescriptionsItem
              v-for="(v, k) in impact.affected.by_label"
              :key="k"
              :label="k"
            >
              {{ v }}
            </ADescriptionsItem>
          </ADescriptions>

          <ACard class="mt" size="small" title="证据路径（图谱）">
            <div class="path-list">
              <div v-for="(p, i) in impact.evidence" :key="i" class="path-row">
                {{ p }}
              </div>
            </div>
          </ACard>
        </template>
        <AAlert
          v-else-if="impact && !impact.found"
          class="mt"
          message="未在图谱中找到该对象，请确认名称"
          type="warning"
          show-icon
        />
      </ACard>

      <ACard class="mt" :body-style="{ padding: '16px 20px' }" title="代码骨架生成">
        <div class="imp-form">
          <AInput
            v-model:value="ifaceId"
            placeholder="接口名（图谱中的 Interface 节点）"
            style="width: 280px"
          />
          <ARadioGroup v-model:value="codeTarget" button-style="solid">
            <ARadioButton value="spring_controller">
              Java · Spring Boot Controller
            </ARadioButton>
            <ARadioButton value="python_script">Python 处理脚本</ARadioButton>
          </ARadioGroup>
          <AButton :loading="codeLoading" type="primary" @click="doCodegen">
            生成骨架
          </AButton>
        </div>

        <template v-if="codegen">
          <AAlert
            class="mt"
            :message="codegen.disclaimer"
            type="info"
            show-icon
          />
          <ATabs class="mt">
            <ATabPane
              v-for="f in codegen.files"
              :key="f.path"
              :tab="f.path"
            >
              <div class="rp-list">
                <ATag v-for="rp in f.review_points" :key="rp" color="orange">
                  需人工校验：{{ rp }}
                </ATag>
              </div>
              <pre class="code-pre">{{ f.content }}</pre>
            </ATabPane>
          </ATabs>
        </template>
      </ACard>
    </div>
  </Page>
</template>

<style lang="scss" scoped>
.imp-wrap {
  display: flex;
  flex-direction: column;
}

.mt {
  margin-top: 12px;
}

.imp-title {
  font-size: 16px;
  font-weight: 600;
}

.imp-sub {
  margin-top: 4px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.imp-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.risk-cell {
  display: flex;
  gap: 8px;
  align-items: center;

  .risk-tag {
    font-size: 16px;
    font-weight: 700;
    text-transform: uppercase;
  }

  .risk-label {
    color: hsl(var(--muted-foreground));
  }
}

.coupling {
  margin-top: 6px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.path-list {
  max-height: 220px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;

  .path-row {
    padding: 2px 0;
  }
}

.rp-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.code-pre {
  max-height: 420px;
  padding: 12px;
  overflow: auto;
  font-family: monospace;
  font-size: 12px;
  line-height: 1.6;
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
}
</style>
