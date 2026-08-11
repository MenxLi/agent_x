<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, Download, File, FileText, Folder, RefreshCw, Trash2, Upload, X } from 'lucide-vue-next'
import { api } from '../api'
import type { AgentInfo, FileEntry } from '../types'

const props = defineProps<{ agents: AgentInfo[]; agentId: string }>()
const emit = defineEmits<{ close: [] }>()

const path = ref('')
const entries = ref<FileEntry[]>([])
const preview = ref<{ path: string; content: string } | null>(null)
const loading = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement>()
const currentAgent = computed(() => props.agents.find(agent => agent.identifier === props.agentId))
const parentPath = computed(() => path.value.split('/').slice(0, -1).join('/'))

watch(() => props.agentId, () => { path.value = ''; preview.value = null; void refresh() })

async function refresh() {
  if (!props.agentId) {
    entries.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    entries.value = (await api.files(props.agentId, path.value)).entries
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Could not load files'
  } finally {
    loading.value = false
  }
}

function open(entry: FileEntry) {
  if (entry.kind === 'directory') {
    path.value = entry.path
    preview.value = null
    void refresh()
  } else if (entry.viewable) {
    void view(entry)
  }
}

async function view(entry: FileEntry) {
  try {
    preview.value = await api.view(props.agentId, entry.path)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Could not preview file'
  }
}

async function upload(files: FileList | null) {
  if (!files?.length) return
  try {
    await api.upload(props.agentId, path.value, Array.from(files))
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Upload failed'
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function remove(entry: FileEntry) {
  if (!window.confirm(`Delete ${entry.name}?`)) return
  try {
    await api.remove(props.agentId, entry.path)
    if (preview.value?.path === entry.path) preview.value = null
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Delete failed'
  }
}

function goUp() {
  path.value = parentPath.value
  preview.value = null
  void refresh()
}

void refresh()
</script>

<template>
  <aside class="file-browser">
    <header class="file-header">
      <div>
        <span class="eyebrow">Workspace</span>
        <strong>{{ currentAgent?.name || 'Files' }}</strong>
      </div>
      <button class="icon-button mobile-close" title="Close files" @click="emit('close')"><X :size="18" /></button>
    </header>

    <div class="file-toolbar">
      <button class="icon-button" title="Parent folder" :disabled="!path" @click="goUp"><ArrowLeft :size="16" /></button>
      <div class="crumb" :title="path || currentAgent?.workdir">{{ path || '/' }}</div>
      <button class="icon-button" title="Refresh" @click="refresh"><RefreshCw :size="16" :class="{ spinning: loading }" /></button>
      <button class="icon-button" title="Upload files" @click="fileInput?.click()"><Upload :size="16" /></button>
      <input ref="fileInput" hidden type="file" multiple @change="upload(($event.target as HTMLInputElement).files)">
    </div>

    <div v-if="error" class="file-error">{{ error }}</div>
    <div class="file-list">
      <div v-if="!loading && !entries.length" class="file-empty">This folder is empty.</div>
      <div v-for="entry in entries" :key="entry.path" class="file-row" @dblclick="open(entry)">
        <button class="file-name" :title="entry.name" @click="open(entry)">
          <Folder v-if="entry.kind === 'directory'" :size="16" />
          <FileText v-else-if="entry.viewable" :size="16" />
          <File v-else :size="16" />
          <span>{{ entry.name }}</span>
        </button>
        <div class="file-actions">
          <a v-if="entry.kind === 'file'" class="icon-button" :href="api.downloadUrl(agentId, entry.path)" :download="entry.name" title="Download"><Download :size="14" /></a>
          <button class="icon-button danger" title="Delete" @click="remove(entry)"><Trash2 :size="14" /></button>
        </div>
      </div>
    </div>

    <section v-if="preview" class="file-preview">
      <header><span>{{ preview.path }}</span><button class="icon-button" title="Close preview" @click="preview = null"><X :size="15" /></button></header>
      <pre>{{ preview.content }}</pre>
    </section>
  </aside>
</template>
