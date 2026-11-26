import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export type ManifestResult = Record<string, any>

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(fallback)
  return (await response.json()) as T
}

export async function previewManifest(payload: Record<string, unknown>): Promise<ManifestResult> {
  const response = await request('/api/file_intake/manifests/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return readJson<ManifestResult>(response, '清单预览失败')
}

export async function importManifest(payload: Record<string, unknown>): Promise<ManifestResult> {
  const response = await request('/api/file_intake/manifests/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return readJson<ManifestResult>(response, '清单提交失败')
}

export async function listManifests(): Promise<{ items: ManifestResult[] }> {
  const response = await request('/api/file_intake/manifests')
  return readJson<{ items: ManifestResult[] }>(response, '清单列表读取失败')
}

export async function getManifest(manifestNo: string): Promise<ManifestResult> {
  const response = await request(`/api/file_intake/manifests/${encodeURIComponent(manifestNo)}`)
  return readJson<ManifestResult>(response, '清单回执读取失败')
}

export async function continueManifest(
  manifestNo: string,
  payload: Record<string, unknown> = {},
): Promise<ManifestResult> {
  const response = await request(
    `/api/file_intake/manifests/${encodeURIComponent(manifestNo)}/continue`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
  return readJson<ManifestResult>(response, '清单续做失败')
}

export async function confirmExternal(payload: Record<string, unknown>): Promise<ManifestResult> {
  const response = await request('/api/file_intake/receipts/external-confirmation', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return readJson<ManifestResult>(response, '外部确认补登失败')
}

export async function reconcileDeliveries(
  payload: Record<string, unknown> = {},
): Promise<ManifestResult> {
  const response = await request('/api/result_deliver/reconcile-fingerprints', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return readJson<ManifestResult>(response, '指纹核销失败')
}

export function sourceFileUrl(receiveNo: string): string {
  const apiBase = import.meta.env.VITE_API_BASE ?? ''
  return `${apiBase}/api/file_intake/files/${encodeURIComponent(receiveNo)}?raw=true`
}

export function targetContentUrl(deliveryNo: string): string {
  const apiBase = import.meta.env.VITE_API_BASE ?? ''
  return `${apiBase}/api/result_deliver/records/${encodeURIComponent(deliveryNo)}/content?raw=true`
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}
