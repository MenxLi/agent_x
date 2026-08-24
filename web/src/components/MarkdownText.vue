<script setup lang="ts">
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import diff from 'highlight.js/lib/languages/diff'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import { marked, Renderer, type Tokens } from 'marked'
import { copyText } from '../clipboard'

const languages = { bash, css, diff, dockerfile, javascript, json, markdown, python, sql, typescript, xml, yaml }
for (const [name, language] of Object.entries(languages)) hljs.registerLanguage(name, language)

const props = defineProps<{ content: string; enabled: boolean; plain?: boolean }>()
let copyTimer = 0

const COPY_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-copy"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>'
const CHECK_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-check"><path d="M20 6 9 17l-5-5"/></svg>'

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

class CodeBlockRenderer extends Renderer {
  override code({ text, lang }: Tokens.Code): string {
    const name = (lang || '').split(/\s+/)[0]
    const language = hljs.getLanguage(name) ? name : ''
    const highlighted = language ? hljs.highlight(text, { language, ignoreIllegals: true }).value : escapeHtml(text)
    const classAttr = language ? ` class="language-${language}"` : ''
    return `<div class="code-block"><pre><code${classAttr}>${highlighted}</code></pre>`
      + `<button type="button" class="code-copy" title="Copy code">${COPY_ICON}${CHECK_ICON}</button></div>`
  }
}

const html = props.plain
  ? ''
  : DOMPurify.sanitize(marked.parse(props.content, { async: false, renderer: new CodeBlockRenderer() }) as string)

function copyCode(button: HTMLElement) {
  const code = button.closest('.code-block')?.querySelector('pre code')?.textContent ?? ''
  void copyText(code).then(() => {
    button.classList.add('copied')
    window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => button.classList.remove('copied'), 1600)
  })
}

function onClick(event: MouseEvent) {
  const button = (event.target as HTMLElement).closest<HTMLElement>('.code-copy')
  if (button) copyCode(button)
}
</script>

<template>
  <div v-if="!plain && enabled" class="markdown" v-html="html" @click="onClick" />
  <div v-else class="plain-text">{{ content }}</div>
</template>

