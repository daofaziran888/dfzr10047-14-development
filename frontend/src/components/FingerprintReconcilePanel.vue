<template>
  <section class="reconcile-panel" data-testid="fingerprint-reconcile-panel">
    <div class="reconcile-head">
      <div>
        <h3>指纹核销批次</h3>
        <p>读取来源清单回执与双指纹结论，区分已经受理/已有实际回执和仍需处理的可投递批次；成功回执不会因单条报错重新上传。</p>
      </div>
      <div class="actions">
        <input
          v-model="manifestNo"
          data-testid="reconcile-manifest-no"
          placeholder="按清单编号过滤，可留空"
        />
        <button class="btn" data-testid="preview-reconcile" type="button" :disabled="busy" @click="preview">
          读取并分类
        </button>
        <button class="btn primary" data-testid="run-reconcile" type="button" :disabled="busy" @click="run">
          核销可投递批次
        </button>
      </div>
    </div>

    <p v-if="message" class="message" :class="{ error: hasFailed }" data-testid="reconcile-message">{{ message }}</p>

    <div v-if="report" class="count-grid" data-testid="reconcile-counts">
      <span>项目总数 <strong>{{ report.counts?.total ?? 0 }}</strong></span>
      <span>已经受理 <strong>{{ report.counts?.already_accepted ?? 0 }}</strong></span>
      <span>仍可投递 <strong>{{ report.counts?.deliverable ?? 0 }}</strong></span>
      <span>已送达 <strong>{{ report.counts?.delivered ?? 0 }}</strong></span>
      <span>本次处理 <strong>{{ report.counts?.processed ?? 0 }}</strong></span>
      <span>阻断/等待 <strong>{{ report.counts?.blocked ?? 0 }}</strong></span>
      <span>失败 <strong>{{ report.counts?.failed ?? 0 }}</strong></span>
    </div>

    <div v-if="report?.items?.length" class="table-scroll">
      <table class="reconcile-table">
        <thead>
          <tr>
            <th>核销分类</th>
            <th>项目/来源</th>
            <th>指纹与内容</th>
            <th>实际收件编号</th>
            <th>投递记录/目标</th>
            <th>说明与核对</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in report.items"
            :key="`${item.receipt?.id ?? index}`"
            :data-testid="`reconcile-row-${item.receipt?.id ?? index}`"
            :data-category="item.category"
          >
            <td><span class="badge" :data-category="item.category">{{ categoryLabel(item.category) }}</span></td>
            <td>
              <strong>{{ item.receipt?.项目标识 }}</strong>
              <div>{{ item.receipt?.来源渠道 || '来源缺失' }}</div>
              <small>{{ item.receipt?.原始文件名 }}</small>
            </td>
            <td>
              <code>{{ item.receipt?.内容指纹 || '—' }}</code>
              <div>{{ item.receipt?.重复判定 || item.receipt?.match_type || '按来源+内容核销' }}</div>
            </td>
            <td data-testid="backfilled-receive-no">
              {{ item.receipt?.实际收件编号 || item.receipt?.收件编号 || '—' }}
            </td>
            <td>
              <div data-testid="backfilled-delivery-no">{{ item.receipt?.投递记录编号 || '尚未生成' }}</div>
              <small>{{ item.receipt?.目标位置 }}</small>
              <small v-if="item.receipt?.目标内容指纹">目标：{{ item.receipt.目标内容指纹 }}</small>
            </td>
            <td>
              <div>{{ item.message }}</div>
              <a
                v-if="item.receipt?.收件编号"
                class="link"
                target="_blank"
                rel="noreferrer"
                :href="sourceFileUrl(item.receipt.收件编号)"
              >
                打开对应文件核对
              </a>
              <a
                v-if="item.receipt?.delivery_no"
                class="link"
                target="_blank"
                rel="noreferrer"
                :href="targetContentUrl(item.receipt.delivery_no)"
              >
                打开目标实际内容
              </a>
              <RouterLink class="link" to="/file_intake">回文件投递工作台</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { reconcileDeliveries, sourceFileUrl, targetContentUrl } from '@/api/backend-service'

const emit = defineEmits<{ changed: [] }>()
const manifestNo = ref('')
const busy = ref(false)
const report = ref<Record<string, any> | null>(null)
const message = ref('')
const hasFailed = ref(false)

async function call(deliver: boolean) {
  busy.value = true
  try {
    const result = await reconcileDeliveries({ manifest_no: manifestNo.value, deliver })
    report.value = result
    message.value = result.message || '核销分类已生成'
    hasFailed.value = Boolean(result.counts?.failed)
    if (deliver) emit('changed')
  } catch (error) {
    message.value = error instanceof Error ? error.message : '指纹核销失败'
    hasFailed.value = true
  } finally {
    busy.value = false
  }
}

function preview() {
  return call(false)
}

function run() {
  return call(true)
}

function categoryLabel(category: string): string {
  const labels: Record<string, string> = {
    delivered_existing: '已受理·已有实际回执',
    delivered_now: '本次核销并送达',
    deliverable: '仍需处理·可投递',
    blocked: '等待/阻断',
    failed: '单项失败',
  }
  return labels[category] ?? category
}

onMounted(() => {
  void preview()
})
</script>

<style scoped>
.reconcile-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 12px 0 16px; }
.reconcile-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.reconcile-panel h3 { margin: 0 0 6px; }
.reconcile-panel p { margin: 4px 0; color: #475569; font-size: 13px; }
.actions { display: flex; gap: 8px; align-items: center; }
.actions input { border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; min-width: 210px; }
.message { padding: 8px 10px; background: #eff6ff; color: #1d4ed8 !important; border-radius: 6px; font-size: 13px; }
.message.error { background: #fef3f2; color: #b42318 !important; }
.count-grid { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.count-grid span { background: #f8fafc; border: 1px solid var(--border); border-radius: 999px; padding: 5px 10px; font-size: 12px; color: #475569; }
.count-grid strong { color: #0f172a; margin-left: 4px; }
.table-scroll { overflow-x: auto; }
.reconcile-table { width: 100%; min-width: 1000px; border-collapse: collapse; }
.reconcile-table th, .reconcile-table td { border: 1px solid var(--border); padding: 7px 8px; font-size: 12px; text-align: left; vertical-align: top; }
.badge { border-radius: 999px; padding: 2px 8px; background: #e0f2fe; color: #075985; white-space: nowrap; }
.badge[data-category='delivered_existing'], .badge[data-category='delivered_now'] { background: #ecfdf3; color: #027a48; }
.badge[data-category='blocked'] { background: #fffaeb; color: #b54708; }
.badge[data-category='failed'] { background: #fef3f2; color: #b42318; }
td .link { display: block; margin-top: 4px; font-size: 12px; }
code { word-break: break-all; }
</style>
