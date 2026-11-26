<template>
  <section class="manifest-panel" data-testid="manifest-import-panel">
    <div class="manifest-panel-head">
      <div>
        <h3>来源文件清单批量登记</h3>
        <p>新增清单导入页内预览，允许补填校验未通过的项目；可勾选本次续做的项目。提交后由服务端按来源和内容核销，给出可跟进到结果投递的逐项受理回执。不同来源分开保存，名字和格式相同也不能互相抵扣。</p>
      </div>
      <div class="manifest-actions">
        <button class="btn primary" data-testid="open-manifest-import" type="button" @click="open = !open">
          {{ open ? '收起清单导入' : '新增清单导入' }}
        </button>
        <select
          class="manifest-select"
          data-testid="manifest-history"
          :value="detail?.清单编号 ?? ''"
          @change="onHistoryChange"
        >
          <option value="">历史受理清单…</option>
          <option v-for="item in manifests" :key="item.清单编号" :value="item.清单编号">
            {{ item.清单编号 }}（{{ item.status }}）
          </option>
        </select>
        <button class="btn" data-testid="refresh-manifests" type="button" @click="loadManifests">刷新</button>
      </div>
    </div>

    <div v-if="open" class="manifest-editor">
      <div class="manifest-sample-actions">
        <label class="file-button btn" data-testid="manifest-upload-label">
          选择上游清单文件
          <input
            type="file"
            data-testid="manifest-file-input"
            accept=".json,.csv,.tsv,.txt"
            @change="onFileSelected"
          />
        </label>
        <button class="btn ghost" data-testid="fill-first-manifest" type="button" @click="fillFirst">
          填入首轮：甲=A1、乙缺来源
        </button>
        <button class="btn ghost" data-testid="fill-second-manifest" type="button" @click="fillSecond">
          填入续报：甲=A2、补齐乙
        </button>
        <span class="hint">支持 JSON 数组、<code>{'{ items: [...] }'}</code> 或带表头 CSV。</span>
      </div>
      <textarea
        v-model="manifestText"
        class="manifest-textarea"
        data-testid="manifest-text"
        placeholder='[{"项目标识":"甲","来源渠道":"sftp-upstream","内容":"A1"}]'
      ></textarea>
      <div class="manifest-actions">
        <button class="btn" data-testid="preview-manifest" type="button" :disabled="busy" @click="preview">
          页内预览
        </button>
        <button
          class="btn primary"
          data-testid="submit-manifest"
          type="button"
          :disabled="busy || !previewRows.length"
          @click="submit"
        >
          提交勾选项目
        </button>
        <button
          class="btn"
          data-testid="repeat-same-manifest"
          type="button"
          :disabled="busy || !previewRows.length"
          @click="submit"
        >
          相同清单再试
        </button>
        <label class="check-inline">
          <input type="checkbox" :checked="allPreviewSelected" @change="toggleAllPreview" />
          全选本次续做
        </label>
        <span v-if="previewResult" class="hint" data-testid="preview-summary">
          共 {{ previewResult.summary?.total ?? previewRows.length }} 项，
          通过 {{ previewResult.summary?.valid ?? 0 }}，
          待补正 {{ previewResult.summary?.invalid ?? 0 }}
        </span>
        <span class="hint">既有成功项目不因一条报错重新上传。</span>
      </div>

      <p v-if="message" class="manifest-message" :class="{ error: isError }" data-testid="manifest-message">
        {{ message }}
      </p>

      <div v-if="previewRows.length" class="table-scroll" data-testid="manifest-preview">
        <table class="manifest-table">
          <thead>
            <tr>
              <th>续做</th>
              <th>项目/文件</th>
              <th>来源渠道（可补填）</th>
              <th>正文/版本（可更正）</th>
              <th>格式</th>
              <th>核销匹配</th>
              <th>校验问题</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in previewRows"
              :key="row.client_id ?? index"
              :data-testid="`preview-row-${row.item_key || index}`"
              :data-valid="String(row.valid)"
            >
              <td>
                <input
                  type="checkbox"
                  :data-testid="`preview-checkbox-${row.item_key || index}`"
                  v-model="row.selected"
                />
              </td>
              <td>
                <input v-model="row.item_key" :data-testid="`preview-key-${index}`" />
                <input v-model="row.file_name" :data-testid="`preview-filename-${index}`" />
              </td>
              <td>
                <input
                  v-model="row.source"
                  :data-testid="`preview-source-${row.item_key || index}`"
                  placeholder="必填，例如 sftp-upstream"
                  :class="{ invalid: row.errors?.来源渠道 }"
                />
              </td>
              <td>
                <input
                  v-model="row.content"
                  :data-testid="`preview-content-${row.item_key || index}`"
                  :class="{ invalid: row.errors?.内容 }"
                />
                <small>{{ row.content_hash || '未计算内容指纹' }}</small>
              </td>
              <td><input v-model="row.file_format" /></td>
              <td>
                <span class="badge" :data-match="row.match_type">{{ row.match_type }}</span>
                <small v-if="row.inbox">{{ row.inbox }}</small>
              </td>
              <td class="error-cell">
                <span v-for="(error, field) in row.errors" :key="field">{{ field }}：{{ error }}<br /></span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="detail" class="receipt-wrap" data-testid="manifest-receipts">
      <div class="receipt-head">
        <div>
          <h4>逐项受理回执：{{ detail.清单编号 }}</h4>
          <p>
            清单指纹 <code>{{ detail.清单指纹 }}</code>；来源范围 {{ detail.来源范围 || '—' }}；
            受理 {{ detail.受理数 }}，待补正 {{ detail.待补正数 }}，待外部确认 {{ detail.待外部确认数 }}，
            已投递 {{ detail.已投递数 }}
          </p>
          <p v-if="reconcileMessage" class="hint" data-testid="reconcile-summary">{{ reconcileMessage }}</p>
        </div>
        <div class="manifest-actions">
          <button class="btn" data-testid="continue-selected" type="button" @click="continueSelected">
            续做勾选回执
          </button>
          <button class="btn primary" data-testid="reconcile-current" type="button" @click="reconcileCurrent">
            读取指纹核销并投递
          </button>
          <RouterLink class="btn" to="/result_deliver">前往结果投递工作台</RouterLink>
        </div>
      </div>

      <div class="table-scroll">
        <table class="manifest-table receipt-table">
          <thead>
            <tr>
              <th>续办</th>
              <th>项目/同名异件</th>
              <th>来源与收件入口</th>
              <th>内容证据</th>
              <th>实际收件编号</th>
              <th>受理/外部确认</th>
              <th>结果投递与目标内容</th>
              <th>核对操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="receipt in detail.receipts"
              :key="receipt.id"
              :data-testid="`receipt-row-${receipt.id}`"
              :data-status="receipt.受理状态"
              :data-receive-no="receipt.实际收件编号 || receipt.收件编号"
            >
              <td><input type="checkbox" v-model="receipt.selected" :data-testid="`receipt-checkbox-${receipt.id}`" /></td>
              <td>
                <strong>{{ receipt.项目标识 }}</strong>
                <div>{{ receipt.原始文件名 }}</div>
                <span v-if="receipt.同名异件 === '是'" class="badge warning" data-testid="same-name-variant">
                  同名异件 · {{ receipt.受理编号 }}
                </span>
                <div v-if="receipt.关联异件?.length" class="hint">关联：{{ receipt.关联异件.join('、') }}</div>
              </td>
              <td>
                <div data-testid="receipt-source">{{ receipt.来源渠道 || '缺失来源' }}</div>
                <small>{{ receipt.收件入口 || '—' }}</small>
              </td>
              <td>
                <code data-testid="content-evidence">{{ receipt.内容指纹 || '—' }}</code>
                <div>标签/正文：{{ receipt.内容标签 || receipt.内容正文 || '—' }}</div>
              </td>
              <td>
                <span data-testid="actual-receive-no">{{ receipt.实际收件编号 || receipt.收件编号 || '尚未生成' }}</span>
                <div class="hint">{{ receipt.受理编号 }}</div>
              </td>
              <td>
                <span class="badge" :data-state="receipt.受理状态">{{ receipt.受理状态 }}</span>
                <div>外部确认：{{ receipt.外部确认 || '未要求' }}</div>
                <small v-if="receipt.外部确认编号">{{ receipt.外部确认编号 }} · {{ receipt.确认时间 }}</small>
                <div v-if="receipt.错误信息" class="error-text">{{ receipt.错误信息 }}</div>
              </td>
              <td>
                <div data-testid="delivery-no">{{ receipt.投递记录编号 || '未生成投递回执' }}</div>
                <a
                  v-if="receipt.投递记录编号 && receipt.目标内容指纹"
                  class="link"
                  target="_blank"
                  rel="noreferrer"
                  :href="targetContentUrl(receipt.投递记录编号)"
                  :data-testid="`verify-target-${receipt.id}`"
                >
                  打开目标实际内容核对
                </a>
                <small v-if="receipt.目标位置">{{ receipt.目标位置 }}</small>
                <div v-if="receipt.目标内容指纹">目标指纹：<code>{{ receipt.目标内容指纹 }}</code></div>
                <div v-if="receipt.目标实际内容">目标内容：{{ receipt.目标实际内容 }}</div>
              </td>
              <td class="receipt-actions">
                <a
                  v-if="receipt.收件编号"
                  class="link"
                  target="_blank"
                  rel="noreferrer"
                  :href="sourceFileUrl(receipt.收件编号)"
                  :data-testid="`verify-file-${receipt.收件编号}`"
                >
                  打开对应文件核对
                </a>
                <button
                  v-if="receipt.外部确认 === '待确认'"
                  class="link"
                  type="button"
                  :data-testid="`confirm-old-${receipt.id}`"
                  @click="confirmOld(receipt)"
                >
                  补到旧确认
                </button>
                <button
                  class="link"
                  type="button"
                  :data-testid="`continue-receipt-${receipt.id}`"
                  @click="continueOne(receipt)"
                >
                  仅续办此项目
                </button>
                <RouterLink v-if="receipt.投递记录编号" class="link" to="/result_deliver">
                  核对投递工作台
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  confirmExternal,
  continueManifest,
  getManifest,
  importManifest,
  listManifests,
  previewManifest,
  reconcileDeliveries,
  sourceFileUrl,
  targetContentUrl,
} from '@/api/backend-service'

const emit = defineEmits<{ changed: [] }>()
const route = useRoute()

const open = ref(route.path.includes('/import') || route.path.includes('/manifests'))
const busy = ref(false)
const manifestText = ref('')
const message = ref('')
const isError = ref(false)
const previewRows = ref<Record<string, any>[]>([])
const previewResult = ref<Record<string, any> | null>(null)
const detail = ref<Record<string, any> | null>(null)
const manifests = ref<Record<string, any>[]>([])
const reconcileMessage = ref('')

const allPreviewSelected = computed({
  get: () => previewRows.value.length > 0 && previewRows.value.every((row) => row.selected),
  set: (value: boolean) => previewRows.value.forEach((row) => { row.selected = value }),
})

function notify(text: string, error = false) {
  message.value = text
  isError.value = error
}

function fillFirst() {
  manifestText.value = JSON.stringify({
    manifest_no: 'SM-UI-DEMO',
    items: [
      {
        item_key: '甲', file_name: '甲.csv', source_channel: 'sftp-upstream',
        content: 'A1', declared_format: 'csv', receive_node: 'inbox-sftp-01',
        external_confirmation: '待确认', parse_status: '已解析',
      },
      {
        item_key: '乙', file_name: '乙.csv', source_channel: '',
        content: '乙-B1', declared_format: 'csv', receive_node: '',
      },
    ],
  }, null, 2)
  notify('已填入首轮清单：甲=A1 等待外部确认，乙缺少来源。')
}

function fillSecond() {
  manifestText.value = JSON.stringify({
    manifest_no: detail.value?.清单编号 || 'SM-UI-DEMO',
    items: [
      {
        item_key: '甲', file_name: '甲.csv', source_channel: 'sftp-upstream',
        content: 'A2', declared_format: 'csv', receive_node: 'inbox-sftp-01',
      },
      {
        item_key: '乙', file_name: '乙.csv', source_channel: 'sftp-partner-02',
        content: '乙-B1', declared_format: 'csv', receive_node: 'inbox-api-02',
      },
    ],
  }, null, 2)
  notify('已填入续报清单：甲同一标识改为 A2（同名异件），乙补齐来源。')
}

async function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  manifestText.value = await file.text()
  notify(`已读取清单文件 ${file.name}，正在生成页内预览…`)
  await preview()
}

async function preview() {
  busy.value = true
  try {
    const payload = parseTextPayload()
    const result = await previewManifest(payload)
    previewResult.value = result
    previewRows.value = (result.items ?? []).map((item: Record<string, any>) => ({ ...item }))
    notify(result.message || '预览完成')
  } catch (error) {
    notify(error instanceof Error ? error.message : '预览失败', true)
  } finally {
    busy.value = false
  }
}

function parseTextPayload(): Record<string, unknown> {
  const text = manifestText.value.trim()
  if (!text) return { items: previewRows.value }
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) return { items: parsed }
    return parsed as Record<string, unknown>
  } catch {
    return { text }
  }
}

async function submit() {
  busy.value = true
  try {
    const payload = parseTextPayload()
    payload.items = previewRows.value
    const result = await importManifest(payload)
    if (!result.ok) throw new Error(result.message || '提交失败')
    detail.value = withSelection(result)
    reconcileMessage.value = ''
    notify(result.message || '清单已受理')
    try {
      const refreshed = await previewManifest({
        manifest_no: payload.manifest_no,
        items: payload.items,
      })
      previewResult.value = refreshed
      previewRows.value = (refreshed.items ?? []).map((item: Record<string, any>) => ({ ...item }))
    } catch {
      // 提交已成功；刷新预览失败时保留当前可编辑行。
    }
    await loadManifests()
    emit('changed')
  } catch (error) {
    notify(error instanceof Error ? error.message : '提交失败', true)
  } finally {
    busy.value = false
  }
}

function withSelection(manifest: Record<string, any>): Record<string, any> {
  for (const receipt of manifest.receipts ?? []) {
    receipt.selected = receipt.受理状态 !== '已投递'
  }
  return manifest
}

async function loadManifests() {
  try {
    const result = await listManifests()
    manifests.value = result.items ?? []
  } catch {
    // 面板仍可通过直接提交工作，列表读取失败不阻断主流程。
  }
}

async function onHistoryChange(event: Event) {
  const manifestNo = (event.target as HTMLSelectElement).value
  if (!manifestNo) return
  try {
    await loadDetail(manifestNo)
  } catch (error) {
    notify(error instanceof Error ? error.message : '清单回执读取失败', true)
  }
}

async function loadDetail(manifestNo: string) {
  const result = await getManifest(manifestNo)
  if (!result.ok) throw new Error(result.message || '清单不存在')
  detail.value = withSelection(result)
}

async function continueReceipts(ids: Array<number | string>) {
  if (!detail.value || !ids.length) {
    notify('请先勾选本次续做的项目', true)
    return
  }
  busy.value = true
  try {
    const result = await continueManifest(detail.value.清单编号, { receipt_ids: ids })
    detail.value = withSelection(result)
    notify(result.message || '续做完成')
    emit('changed')
  } catch (error) {
    notify(error instanceof Error ? error.message : '续做失败', true)
  } finally {
    busy.value = false
  }
}

function continueSelected() {
  const ids = (detail.value?.receipts ?? [])
    .filter((receipt: Record<string, any>) => receipt.selected)
    .map((receipt: Record<string, any>) => receipt.id)
  return continueReceipts(ids)
}

function continueOne(receipt: Record<string, any>) {
  return continueReceipts([receipt.id])
}

async function confirmOld(receipt: Record<string, any>) {
  busy.value = true
  try {
    const result = await confirmExternal({ receipt_id: receipt.id })
    if (!result.ok) throw new Error(result.message || '外部确认失败')
    notify(result.message)
    if (detail.value) await loadDetail(detail.value.清单编号)
    emit('changed')
  } catch (error) {
    notify(error instanceof Error ? error.message : '外部确认失败', true)
  } finally {
    busy.value = false
  }
}

async function reconcileCurrent() {
  if (!detail.value) return
  busy.value = true
  try {
    const result = await reconcileDeliveries({ manifest_no: detail.value.清单编号 })
    reconcileMessage.value = result.message
    if (!result.ok) notify(result.message || '核销存在失败项', true)
    else notify(result.message || '核销完成')
    await loadDetail(detail.value.清单编号)
    await loadManifests()
    emit('changed')
  } catch (error) {
    notify(error instanceof Error ? error.message : '核销失败', true)
  } finally {
    busy.value = false
  }
}

function toggleAllPreview(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  previewRows.value.forEach((row) => { row.selected = checked })
}

onMounted(loadManifests)
</script>

<style scoped>
.manifest-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 12px 0 16px; }
.manifest-panel-head, .receipt-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.manifest-panel h3, .manifest-panel h4 { margin: 0 0 6px; }
.manifest-panel p { margin: 4px 0; font-size: 13px; color: #475569; }
.manifest-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.manifest-select { min-width: 190px; border: 1px solid var(--border); border-radius: 6px; padding: 7px 8px; }
.manifest-editor { border-top: 1px solid #eef2f7; margin-top: 12px; padding-top: 12px; }
.manifest-sample-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.file-button { position: relative; overflow: hidden; cursor: pointer; }
.file-button input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.manifest-textarea { width: 100%; min-height: 150px; border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.check-inline { font-size: 13px; display: inline-flex; gap: 4px; align-items: center; }
.hint { color: var(--muted); font-size: 12px; }
.manifest-message { padding: 8px 10px; background: #eff6ff; border-radius: 6px; color: #1d4ed8 !important; }
.manifest-message.error { background: #fef3f2; color: #b42318 !important; }
.table-scroll { overflow-x: auto; margin-top: 10px; }
.manifest-table { width: 100%; border-collapse: collapse; min-width: 900px; }
.manifest-table th, .manifest-table td { border: 1px solid var(--border); padding: 7px 8px; font-size: 12px; vertical-align: top; text-align: left; }
.manifest-table input { width: 100%; min-width: 110px; border: 1px solid #d8dee6; border-radius: 5px; padding: 5px 6px; margin-bottom: 4px; }
.manifest-table input.invalid { border-color: #d92d20; background: #fff1f0; }
.manifest-table small { display: block; color: var(--muted); word-break: break-all; }
.badge { display: inline-block; border-radius: 999px; padding: 2px 8px; background: #e0f2fe; color: #075985; font-size: 12px; margin: 1px 0; }
.badge.warning, .badge[data-state='待外部确认'] { background: #fffaeb; color: #b54708; }
.badge[data-state='待补正'], .badge[data-state='失败'] { background: #fef3f2; color: #b42318; }
.badge[data-state='已投递'] { background: #ecfdf3; color: #027a48; }
.error-cell, .error-text { color: #b42318; }
.receipt-wrap { border-top: 1px solid #eef2f7; margin-top: 14px; padding-top: 12px; }
.receipt-table { min-width: 1180px; }
.receipt-actions { display: flex; flex-direction: column; gap: 6px; white-space: nowrap; }
.receipt-actions .link { font-size: 12px; }
code { word-break: break-all; }
</style>
