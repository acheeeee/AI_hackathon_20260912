<script setup lang="ts">
defineProps<{
  subtitle?: string
  geminiOn?: boolean
  statusText?: string
  statusTone?: 'ok' | 'plain'
  showLegacyBadge?: boolean
}>()
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <img src="@/assets/bedo-logo.svg" alt="BEDO" class="logo" />
      <div class="brand-text">
        <div class="title">新北市政府訴願管理 AI 輔助系統</div>
        <div class="subtitle">
          {{ subtitle || 'Appeals Management AI Assistant　·　程序審查｜法規推薦｜相似前例｜草稿生成' }}
        </div>
      </div>
    </div>
    <div class="badges">
      <span v-if="statusText" class="badge" :class="statusTone === 'ok' ? 'badge-ok' : 'badge-plain'">
        {{ statusText }}
      </span>
      <span v-if="showLegacyBadge" class="badge badge-plain">承辦人　王○明</span>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  background: linear-gradient(100deg, #0b3d91, #1a56c4);
  color: #ffffff;
  padding: 14px 28px;
  box-shadow: var(--shadow);
}

.brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  height: 52px;
  width: auto;
}

.title {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.5px;
}

.subtitle {
  font-size: 12px;
  opacity: 0.85;
  margin-top: 2px;
}

.badges {
  display: flex;
  align-items: center;
  gap: 10px;
}

.badge {
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 20px;
  white-space: nowrap;
}

.badge-ok {
  background: rgba(26, 127, 75, 0.9);
}

.badge-plain {
  background: rgba(255, 255, 255, 0.15);
}
</style>
