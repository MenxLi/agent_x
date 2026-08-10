import type { AgentInfo, CommandInfo, FileListing } from './types'

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
  events: () => request<import('./types').DisplayEvent[]>('/api/events'),
  agents: () => request<AgentInfo[]>('/api/agents'),
  commands: () => request<CommandInfo[]>('/api/commands'),
  files: (agentId: string, path = '') =>
    request<FileListing>(`/api/files?${query({ agent_id: agentId, path })}`),
  view: (agentId: string, path: string) =>
    request<{ path: string; content: string }>(`/api/files/view?${query({ agent_id: agentId, path })}`),
  downloadUrl: (agentId: string, path: string) =>
    `/api/files/download?${query({ agent_id: agentId, path })}`,
  upload: (agentId: string, path: string, files: File[]) => {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    return request<{ uploaded: string[] }>(
      `/api/files/upload?${query({ agent_id: agentId, path })}`,
      { method: 'POST', body },
    )
  },
  remove: (agentId: string, path: string) =>
    request<{ deleted: boolean }>(`/api/files?${query({ agent_id: agentId, path })}`, { method: 'DELETE' }),
}
