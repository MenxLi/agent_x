import type { AgentInfo, CommandInfo, DisplayEvent, FileListing, ModelCapabilities, PendingPrompt, WebConfig } from './types'

const configuredBasePath = import.meta.env.VITE_XUN_BASE_PATH as string | undefined
export const basePath = (configuredBasePath ?? location.pathname).replace(/\/$/, '')

export function appUrl(path: string): string {
  return `${basePath}${path}`
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

function query(params: Record<string, string>): string {
  return new URLSearchParams(params).toString()
}

export const api = {
  config: () => request<WebConfig>(appUrl('/api/config')),
  events: () => request<DisplayEvent[]>(appUrl('/api/events')),
  prompt: () => request<PendingPrompt | null>(appUrl('/api/prompt')),
  resolvePrompt: (promptId: string, value: string) => request<{ resolved: boolean }>(
    appUrl(`/api/prompt/${encodeURIComponent(promptId)}`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'choice', prompt_id: promptId, value }),
    },
  ),
  agents: () => request<AgentInfo[]>(appUrl('/api/agents')),
  running: () => request<string[]>(appUrl('/api/running')),
  commands: (agentId: string) => request<CommandInfo[]>(appUrl(`/api/commands/${encodeURIComponent(agentId)}`)),
  capabilities: (agentId: string) => request<ModelCapabilities>(appUrl(`/api/capabilities/${encodeURIComponent(agentId)}`)),
  files: (agentId: string, path = '') =>
    request<FileListing>(appUrl(`/api/files/${encodeURIComponent(agentId)}?${query({ path })}`)),
  view: (agentId: string, path: string) =>
    request<{ path: string; content: string }>(appUrl(`/api/files/${encodeURIComponent(agentId)}/view?${query({ path })}`)),
  downloadUrl: (agentId: string, path: string) =>
    appUrl(`/api/files/${encodeURIComponent(agentId)}/download?${query({ path })}`),
  upload: (agentId: string, path: string, files: File[]) => {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    return request<{ uploaded: string[] }>(
      appUrl(`/api/files/${encodeURIComponent(agentId)}/upload?${query({ path })}`),
      { method: 'POST', body },
    )
  },
  remove: (agentId: string, path: string) =>
    request<{ deleted: boolean }>(appUrl(`/api/files/${encodeURIComponent(agentId)}?${query({ path })}`), { method: 'DELETE' }),
}
