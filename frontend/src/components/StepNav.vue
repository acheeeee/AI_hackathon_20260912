<script setup lang="ts">
import { computed } from 'vue'
import { useCaseStore, STEP_ORDER, STEP_LABELS, type StepKey } from '@/stores/case'

const caseStore = useCaseStore()

const activeIndex = computed(() => STEP_ORDER.indexOf(caseStore.step))

// 只有分析完成後才可點擊跳步；upload 永遠可回去。
function stepState(key: StepKey, index: number): 'done' | 'active' | 'todo' {
  if (index < activeIndex.value) return 'done'
  if (index === activeIndex.value) return 'active'
  return 'todo'
}

function reachable(index: number): boolean {
  if (index === 0) return true
  return caseStore.hasResult && index <= Math.max(activeIndex.value, 1) + 3
}

function onStep(key: StepKey, index: number) {
  if (reachable(index)) caseStore.goTo(key)
}
</script>

<template>
  <nav class="stepbar">
    <div class="steps">
      <template v-for="(key, i) in STEP_ORDER" :key="key">
        <button
          type="button"
          class="step"
          :class="[stepState(key, i), { clickable: reachable(i) }]"
          @click="onStep(key, i)"
        >
          <span v-if="stepState(key, i) === 'done'" class="ring done-ring">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="9" stroke-width="1.6" />
              <path d="m8 12 3 3 5-6" />
            </svg>
          </span>
          <span v-else class="num" :class="stepState(key, i)">{{ i + 1 }}</span>
          <span class="label">{{ STEP_LABELS[key] }}</span>
        </button>
        <span v-if="i < STEP_ORDER.length - 1" class="sep" />
      </template>
    </div>
  </nav>
</template>

<style scoped>
.stepbar {
  background: #ffffff;
  border-bottom: 1px solid var(--line);
}

.steps {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 20px;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 14px;
  border: none;
  background: transparent;
  border-radius: 20px;
  font-family: inherit;
  color: var(--muted);
  cursor: default;
}

.step.clickable {
  cursor: pointer;
}

.step.active {
  background: var(--blue);
  color: #ffffff;
}

.step.done {
  color: var(--ok);
}

.label {
  font-size: 14px;
}

.step.active .label {
  font-weight: 700;
}

.num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.num.todo {
  border: 1.5px solid var(--line-strong);
}

.num.active {
  background: var(--yellow);
  color: var(--blue);
  font-weight: 900;
}

.ring {
  display: flex;
  align-items: center;
  justify-content: center;
}

.done-ring {
  color: var(--ok);
}

.sep {
  width: 22px;
  height: 1px;
  background: var(--line);
  flex: none;
}
</style>
