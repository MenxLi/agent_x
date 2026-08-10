export interface AgentInfo {
  id: string
  name: string
  workdir: string
}

export interface CommandInfo {
  name: string
  description: string
}

export interface DisplayEvent {
  name: string
  agent: { name: string; identifier: string; workdir: string } | null
  event: Record<string, unknown>
}

export interface PendingPrompt {
  prompt: string
  choices: string[]
  message?: string
  title?: string
  subtitle?: string
  default?: string
  allow_extra?: boolean
}

export interface FileEntry {
  name: string
  path: string
  kind: 'file' | 'directory'
  size: number | null
  viewable: boolean
}

export interface FileListing {
  path: string
  entries: FileEntry[]
}
