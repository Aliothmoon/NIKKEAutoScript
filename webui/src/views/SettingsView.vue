<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import { MIRRORCHYAN_TIP, UPDATE_SOURCE_HELP, t } from '../i18n'
import { useSystemStore } from '../stores/system'
import { useUpdateStore } from '../stores/update'

const { systemStatus, updateInfo } = storeToRefs(useSystemStore())
const update = useUpdateStore()
const { isDesktopShell, desktopUpdate, desktopChecking, desktopApplying, updateChecking, updating, restarting, sourceSaving } = storeToRefs(update)
const { checkDesktopUpdate, applyDesktopUpdate, checkUpdate, runUpdate, forceRestart, saveUpdateSource, saveMirrorChyanCdk } = update
// git 不可用（fetch 失败等）时后端会返回 [null,...] 占位，过滤掉避免渲染整页崩溃
const historyCommits = computed(() => ((updateInfo.value.history || []) as any[]).filter(commit => commit && commit[0]))

type UpdateSource = 'git' | 'mirrorchyan'
// 选中哪个更新源就立即生效；Mirror酱 的 CDK 单独保存
const source = computed(() => updateInfo.value.source || { type: 'git', cdk_set: false, cdk_tail: '', mirrorchyan_available: false })
const cdkInput = ref('')
const revealCdk = ref(false)
const cdkField = ref<HTMLInputElement | null>(null)
const cdkPlaceholder = computed(() => source.value.cdk_set
  ? `${t('已保存 CDK')} ····${source.value.cdk_tail} · ${t('输入新的 CDK 可替换')}`
  : t('输入 Mirror酱 CDK'))
async function pickSource(type: UpdateSource) {
  if (sourceSaving.value || type === source.value.type) return
  if (await saveUpdateSource(type) && type === 'mirrorchyan' && !source.value.cdk_set) {
    await nextTick()
    cdkField.value?.focus()
  }
}
// CDK 在输入框失去焦点时自动保存（回车同样）：空输入保留已保存的 CDK，
// 校验失败的值保留在框里供修改，原样再次失焦不会重复提交
const cdkVerifying = ref(false)
let cdkRejected = ''
async function saveCdk() {
  const cdk = cdkInput.value.trim()
  if (!cdk || cdk === cdkRejected || cdkVerifying.value) return
  cdkVerifying.value = true
  try {
    if (await saveMirrorChyanCdk(cdk)) {
      cdkInput.value = ''
      cdkRejected = ''
    } else {
      cdkRejected = cdk
    }
  } finally { cdkVerifying.value = false }
}
// CDK 状态：后端每次用 CDK 检查或保存时更新；有问题时显示原因，否则显示剩余天数
const cdkStatus = computed(() => {
  if (cdkVerifying.value) return { text: t('验证中…'), level: 'muted', title: '' }
  if (!source.value.cdk_set) return { text: t('未填写 CDK'), level: 'warn', title: '' }
  const info = updateInfo.value.mirrorchyan_cdk
  if (!info) return null
  if (info.error) return { text: String(info.error), level: 'error', title: '' }
  const expires = Number(info.expires) * 1000
  if (!expires) return null
  const title = new Date(expires).toLocaleString()
  if (expires <= Date.now()) return { text: t('CDK 已过期，请使用新的 CDK'), level: 'error', title }
  const days = Math.ceil((expires - Date.now()) / 86400000)
  return { text: t('CDK 还剩 {0} 天到期').replace('{0}', String(days)), level: days <= 7 ? 'warn' : 'ok', title }
})
// Mirror酱 更新后 git 历史只到它下发的版本，新版本的内容来自 release note
const mirrorchyanLatest = computed(() => Number(updateInfo.value.state) === 1 ? updateInfo.value.mirrorchyan_latest : null)
const releaseNoteLines = computed(() => String(mirrorchyanLatest.value?.release_note || '').split('\n').map(line => line.trim()).filter(Boolean))
</script>

<template>
  <section class="view">
    <article class="card task-hero">
      <div class="task-icon"><AppIcon name="monitor" :size="22" /></div>
      <div style="flex:1"><h2>{{ t('启动器更新') }}</h2><div class="sub">{{ t('更新nkas程序（exe）本身') }}<span v-if="!isDesktopShell" class="desktop-only-hint"> · {{ t('此功能仅在1.x版本中可用') }}</span></div>
        <div class="sub">{{ t('当前版本') }} <code class="ver-pill">{{ desktopUpdate?.currentVersion || '—' }}</code><span v-if="desktopUpdate?.updateAvailable" class="update-hint"> · {{ t('有新版本可用') }}</span><span v-else-if="desktopUpdate?.checked && !desktopUpdate?.error" class="sub"> · {{ t('已是最新') }}</span><span v-if="desktopUpdate?.error" class="update-hint"> · {{ desktopUpdate.error }}</span></div>
      </div>
      <button v-if="desktopUpdate?.updateAvailable" class="btn success" :disabled="!isDesktopShell || desktopApplying || desktopUpdate?.applying" @click="applyDesktopUpdate"><span v-if="desktopApplying || desktopUpdate?.applying" class="btn-spin"></span><AppIcon name="download" :size="15" color="currentColor" /> {{ desktopApplying || desktopUpdate?.applying ? t('更新中…') : t('立即更新') }}</button>
      <button v-else class="btn primary" :disabled="!isDesktopShell || desktopChecking || desktopApplying || desktopUpdate?.checking || desktopUpdate?.applying" @click="checkDesktopUpdate"><span v-if="desktopChecking || desktopApplying || desktopUpdate?.checking || desktopUpdate?.applying" class="btn-spin"></span><AppIcon name="refresh" :size="15" color="currentColor" /> {{ desktopApplying || desktopUpdate?.applying ? t('更新中…') : (desktopChecking || desktopUpdate?.checking ? t('检查中…') : t('检查更新')) }}</button>
    </article>
    <article class="card task-hero source-card">
      <div class="task-icon"><AppIcon name="rocket" :size="22" /></div>
      <div style="flex:1"><h2>{{ t('源码更新') }}</h2><div class="sub">{{ t('当前版本') }} <code class="ver-pill">{{ systemStatus.version }}</code><span v-if="Number(updateInfo.state) === 1" class="update-hint"> · {{ t('有新版本可用') }}</span><span v-else-if="Number(updateInfo.state) === 0" class="sub"> · {{ t('已是最新') }}</span><span v-else-if="updateInfo.state === 'failed'" class="update-error"> · {{ updateInfo.error ? t('检查更新失败') : t('更新失败') }}<span v-if="updateInfo.error">：{{ updateInfo.error }}</span></span></div>
        <div class="update-source">
          <span class="update-source-label">{{ t('更新源') }}</span>
          <span class="source-help" tabindex="0" :aria-label="t('什么是 Mirror酱？')">
            <AppIcon name="info-circle" :size="15" />
            <span class="source-help-pop" role="tooltip">{{ t(UPDATE_SOURCE_HELP) }}</span>
          </span>
          <button type="button" class="deploy-multi-opt" :class="{ on: source.type === 'git' }" :disabled="sourceSaving" @click="pickSource('git')">Git</button>
          <button type="button" class="deploy-multi-opt" :class="{ on: source.type === 'mirrorchyan' }" :disabled="sourceSaving || !source.mirrorchyan_available" :title="source.mirrorchyan_available ? '' : t('Mirror酱 只提供官方仓库 master 分支的更新')" @click="pickSource('mirrorchyan')">Mirror酱</button>
          <span v-if="sourceSaving" class="btn-spin"></span>
          <span v-else-if="!source.mirrorchyan_available" class="sub">{{ t('Mirror酱 只提供官方仓库 master 分支的更新') }}</span>
        </div>
        <template v-if="source.type === 'mirrorchyan'">
          <div class="update-source-tip">{{ t(MIRRORCHYAN_TIP) }}</div>
          <div class="update-source-cdk">
            <input ref="cdkField" v-model="cdkInput" :type="revealCdk ? 'text' : 'password'" :placeholder="cdkPlaceholder" :disabled="cdkVerifying" autocomplete="off" spellcheck="false" @blur="saveCdk" @keyup.enter="cdkField?.blur()">
            <!-- 不抢输入框焦点：查看刚输入的 CDK 时不触发保存 -->
            <button type="button" class="btn" @mousedown.prevent @click="revealCdk = !revealCdk">{{ revealCdk ? t('隐藏') : t('显示') }}</button>
            <a class="btn" href="https://mirrorchyan.com" target="_blank" rel="noopener noreferrer">{{ t('获取 CDK') }}</a>
          </div>
          <div v-if="cdkStatus" class="cdk-status" :class="cdkStatus.level" :title="cdkStatus.title">{{ cdkStatus.text }}</div>
        </template>
      </div>
      <button v-if="Number(updateInfo.state) === 1" class="btn success" :disabled="updating" @click="runUpdate"><span v-if="updating" class="btn-spin"></span><AppIcon name="download" :size="15" color="currentColor" /> {{ updating ? t('更新中…') : t('立即更新') }}</button>
      <!-- "failed" with an error message means the *check* failed (e.g.
           network), so offer re-check instead of a full update+restart;
           an empty error means a real update run failed, offer retry. -->
      <button v-else-if="updateInfo.state === 'failed' && !updateInfo.error" class="btn danger" :disabled="updating" @click="runUpdate"><span v-if="updating" class="btn-spin"></span><AppIcon name="refresh" :size="15" color="currentColor" /> {{ updating ? t('更新中…') : t('重试更新') }}</button>
      <button v-else class="btn primary" :disabled="updating || updateChecking || updateInfo.state === 'checking'" @click="checkUpdate"><AppIcon name="refresh" :size="15" color="currentColor" /> {{ updating ? t('更新中…') : (updateChecking || updateInfo.state === 'checking' ? t('检查中…') : t('检查更新')) }}</button>
      <button class="btn danger" :disabled="restarting" @click="forceRestart"><span v-if="restarting" class="btn-spin"></span><AppIcon name="power" :size="15" /> {{ restarting ? t('重启中…') : t('强制重启') }}</button>
    </article>
    <article class="card group-card">
      <div class="group-head"><h4>{{ t('更新记录') }}</h4></div>
      <div class="group-body history-body">
        <div v-if="mirrorchyanLatest" class="history-row mirrorchyan-latest"><span class="msg">{{ t('Mirror酱 新版本') }}</span><small><code>{{ mirrorchyanLatest.version_name }}</code></small>
          <ul v-if="releaseNoteLines.length" class="release-note"><li v-for="(line, index) in releaseNoteLines" :key="index">{{ line.replace(/^[-*]\s*/, '') }}</li></ul>
        </div>
        <div v-for="commit in historyCommits" :key="commit[0]" class="history-row" :class="{ current: updateInfo.local?.[0] && commit[0] === updateInfo.local[0] }"><span class="msg">{{ commit[3] }}</span><small><code>{{ commit[0] }}</code><span v-if="updateInfo.local?.[0] && commit[0] === updateInfo.local[0]" class="current-pill">{{ t('当前版本') }}</span>{{ String(commit[2] || '').slice(0, 10) }}</small></div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.update-source { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:12px; }
.update-source-label { margin-right:4px; color:var(--text-2); font-size:13px; }
.update-source .deploy-multi-opt { font:inherit; font-size:12.5px; }
.update-source .deploy-multi-opt:disabled { opacity:.5; cursor:not-allowed; }
.update-source .sub { font-size:12px; }
.update-source-cdk { display:flex; gap:8px; align-items:center; max-width:640px; margin-top:10px; }
.update-source-cdk input { flex:1; min-width:0; height:36px; padding:0 11px; border:1px solid var(--border); border-radius:9px; outline:0; color:var(--text); background:var(--card-2); }
.update-source-cdk input:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
.update-source-cdk .btn { flex:none; text-decoration:none; }
.mirrorchyan-latest { background:var(--accent-soft); }
.mirrorchyan-latest .msg { font-weight:600; }
.release-note { margin:6px 0 0; padding-left:18px; color:var(--text-2); font-size:13px; }
.release-note li { margin:2px 0; }
/* the rise animation makes every card a stacking context, so the help bubble would
   paint under the next card; this card goes above its siblings instead */
.source-card { z-index:2; }
.source-help { position:relative; display:inline-flex; align-items:center; margin:0 4px 0 -2px; color:var(--text-3); cursor:help; outline:0; }
.source-help:focus-visible { border-radius:50%; outline:2px solid var(--accent); outline-offset:2px; }
.source-help-pop { display:none; position:absolute; z-index:20; top:calc(100% + 8px); left:-14px; width:min(480px,70vw); padding:12px 14px; border:1px solid var(--border); border-radius:10px; color:var(--text); background:var(--card); box-shadow:var(--shadow-hover); font-size:12.5px; line-height:1.7; white-space:pre-wrap; cursor:auto; }
.source-help:hover .source-help-pop, .source-help:focus .source-help-pop { display:block; }
.update-source-tip { max-width:640px; margin-top:8px; color:var(--text-3); font-size:12.5px; line-height:1.5; }
.cdk-status { margin-top:6px; font-size:12.5px; }
.cdk-status.ok { color:var(--green); }
.cdk-status.warn { color:var(--yellow); }
.cdk-status.error { color:var(--red); }
.cdk-status.muted { color:var(--text-3); }
</style>
