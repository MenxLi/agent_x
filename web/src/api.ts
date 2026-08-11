import type { AgentInfo, CommandInfo, DisplayEvent, FileListing, ModelCapabilities } from './types'

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
  events: () => request<DisplayEvent[]>(appUrl('/api/events')),
  agents: () => request<AgentInfo[]>(appUrl('/api/agents')),
  commands: () => request<CommandInfo[]>(appUrl('/api/commands')),
  capabilities: () => request<ModelCapabilities>(appUrl('/api/capabilities')),
  files: (agentId: string, path = '') =>
    request<FileListing>(appUrl(`/api/files?${query({ agent_id: agentId, path })}`)),
  view: (agentId: string, path: string) =>
    request<{ path: string; content: string }>(appUrl(`/api/files/view?${query({ agent_id: agentId, path })}`)),
  downloadUrl: (agentId: string, path: string) =>
    appUrl(`/api/files/download?${query({ agent_id: agentId, path })}`),
  upload: (agentId: string, path: string, files: File[]) => {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    return request<{ uploaded: string[] }>(
      appUrl(`/api/files/upload?${query({ agent_id: agentId, path })}`),
      { method: 'POST', body },
    )
  },
  remove: (agentId: string, path: string) =>
    request<{ deleted: boolean }>(appUrl(`/api/files?${query({ agent_id: agentId, path })}`), { method: 'DELETE' }),
}
