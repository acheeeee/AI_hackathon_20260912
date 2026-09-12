<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { checkHealth } from '@/api/client'

const apiStatus = ref('連線檢查中…')
const apiOk = ref(false)

onMounted(async () => {
  try {
    const health = await checkHealth()
    apiOk.value = true
    apiStatus.value = health.gemini
      ? '🟢 Gemini 已連線（向量檢索＋草稿生成啟用）'
      : '🟡 未設定 API key（降級為 BM25 檢索＋模板草稿）'
  } catch {
    apiOk.value = false
    apiStatus.value = '🔴 無法連線到後端 API'
  }
})
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <img src="@/assets/bedo-logo.svg" alt="BEDO" class="logo" />
      <div class="brand-text">
        <h1>新北市政府訴願管理 AI 輔助系統</h1>
        <p>Appeals Management AI Assistant　·　法規推薦｜時效提示｜相似案例｜草稿生成</p>
      </div>
    </div>
    <div class="api-status" :class="{ ok: apiOk }">{{ apiStatus }}</div>
  </header>

  <RouterView />
</template>

<style scoped>
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid var(--el-border-color);
  margin-bottom: 20px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  height: 40px;
}

.brand-text h1 {
  font-size: 18px;
  margin: 0;
}

.brand-text p {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 2px 0 0;
}

.api-status {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.api-status.ok {
  color: var(--el-color-success);
}
</style>
