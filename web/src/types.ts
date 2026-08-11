export interface AgentInfo {
  identifier: string
  name: string
  workdir: string
}

export interface CommandInfo {
  name: string
  description: string
}

type EventEnvelope<Name extends string, Payload> = {
  name: Name
  agent: AgentInfo | null
  event: Payload
}

export type ToolCallDisplayEvent = EventEnvelope<'ToolCallEvent', {
  tool_call_id: string
  tool_name: string
  args: Record<string, unknown>
}>

export type ToolResultDisplayEvent = EventEnvelope<'ToolResultEvent', {
  tool_call_id: string
  result: unknown
}>

export interface ImageDescriptor {
  kind: 'url' | 'base64'
  value: string
}

export type DisplayEvent =
  | EventEnvelope<'AgentBindEvent', Record<string, never>>
  | EventEnvelope<'AgentUnbindEvent', Record<string, never>>
  | EventEnvelope<'ModelWorkingEvent', { model_call_id: string; remaining_iterations?: number | null }>
  | EventEnvelope<'ModelMessageEvent', { model_call_id: string; content: string }>
  | ToolCallDisplayEvent
  | ToolResultDisplayEvent
  | EventEnvelope<'ShowHistoryEvent', { history: Array<{ role: string; content: unknown }> }>
  | EventEnvelope<'ShowHelpEvent', { commands: CommandInfo[] }>
  | EventEnvelope<'UserCommandEvent', { name: string; arguments?: string | null }>
  | EventEnvelope<'UserMessageEvent', { content: string; images: ImageDescriptor[] }>
  | EventEnvelope<'InfoEvent', { message: string }>
  | EventEnvelope<'WarningEvent', { message: string }>
  | EventEnvelope<'ErrorEvent', { message: string }>

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

export interface ModelCapabilities {
  model: string
  capabilities: Array<'vision'>
}

export type ServerMessage = DisplayEvent | { type: 'pending_prompt'; data: PendingPrompt }

export type ClientMessage =
  | { type: 'message'; agent_id: string; content: string; images: ImageDescriptor[] }
  | { type: 'command'; agent_id: string; name: string; arguments: string | null }
  | { type: 'choice'; value: string }
