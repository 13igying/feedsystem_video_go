<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createBug, listBugs, updateBugStatus, type BugWithNames } from '../api/bug'
import { listAccounts, type AccountBrief } from '../api/account'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const bugs = ref<BugWithNames[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')
const filterStatus = ref('')
const filterRole = ref('')
const accounts = ref<AccountBrief[]>([])

const form = ref({ title: '', description: '', severity: 'minor', assignee_id: '' })
const submitting = ref(false)

const severityOptions = [
  { value: 'critical', label: '致命' },
  { value: 'major', label: '严重' },
  { value: 'minor', label: '一般' },
  { value: 'trivial', label: '轻微' },
]

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'open', label: '待处理' },
  { value: 'fixing', label: '修复中' },
  { value: 'fixed', label: '待回归' },
  { value: 'closed', label: '已关闭' },
]

const severityClass: Record<string, string> = {
  critical: 'sev-critical',
  major: 'sev-major',
  minor: 'sev-minor',
  trivial: 'sev-trivial',
}

const statusLabel: Record<string, string> = {
  open: '待处理',
  fixing: '修复中',
  fixed: '待回归',
  closed: '已关闭',
}

// 当前用户对每个 bug 可执行的状态动作
function availableActions(bug: BugWithNames): { status: string; label: string }[] {
  const uid = auth.claims?.account_id
  const actions: { status: string; label: string }[] = []
  if (bug.status === 'open') {
    if (bug.assignee_id === uid) {
      actions.push({ status: 'fixing', label: '开始修复' })
      actions.push({ status: 'fixed', label: '直接修复完成' })
    }
    if (bug.reporter_id === uid) actions.push({ status: 'closed', label: '直接关闭' })
  } else if (bug.status === 'fixing') {
    if (bug.assignee_id === uid) actions.push({ status: 'fixed', label: '修复完成' })
  } else if (bug.status === 'fixed') {
    if (bug.reporter_id === uid) {
      actions.push({ status: 'closed', label: '回归通过' })
      actions.push({ status: 'open', label: '回归失败打回' })
    }
  }
  return actions
}

async function loadAccounts() {
  try {
    const resp = await listAccounts()
    accounts.value = resp.accounts ?? []
  } catch {
    // 拉取成员列表失败时保持空数组，表单回退为手填负责人 ID
    accounts.value = []
  }
}

async function refresh() {
  loading.value = true
  errorMsg.value = ''
  try {
    const resp = await listBugs({ status: filterStatus.value, role: filterRole.value, limit: 50 })
    bugs.value = resp.bugs ?? []
    total.value = resp.total ?? 0
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!form.value.title.trim() || !form.value.assignee_id) {
    errorMsg.value = '标题和负责人为必填项'
    return
  }
  submitting.value = true
  errorMsg.value = ''
  try {
    await createBug({
      title: form.value.title.trim(),
      description: form.value.description.trim(),
      severity: form.value.severity,
      assignee_id: Number(form.value.assignee_id),
    })
    form.value = { title: '', description: '', severity: 'minor', assignee_id: '' }
    await refresh()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}

async function changeStatus(bugId: number, status: string) {
  errorMsg.value = ''
  try {
    await updateBugStatus(bugId, status)
    await refresh()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(() => {
  refresh()
  loadAccounts()
})
</script>

<template>
  <div class="bug-view">
    <h1>Bug 跟踪</h1>
    <p v-if="errorMsg" class="error">{{ errorMsg }}</p>

    <section class="card">
      <h2>提交新 Bug</h2>
      <form class="bug-form" @submit.prevent="submit">
        <input v-model="form.title" placeholder="标题（必填）" />
        <select v-if="accounts.length" v-model="form.assignee_id">
          <option value="" disabled>选择负责人（必选）</option>
          <option v-for="a in accounts" :key="a.id" :value="String(a.id)">{{ a.username }}（#{{ a.id }}）</option>
        </select>
        <input v-else v-model="form.assignee_id" placeholder="负责人 ID（必填）" type="number" min="1" />
        <select v-model="form.severity">
          <option v-for="opt in severityOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <textarea v-model="form.description" placeholder="复现步骤 / 描述" rows="3"></textarea>
        <button type="submit" :disabled="submitting">{{ submitting ? '提交中…' : '提交' }}</button>
      </form>
    </section>

    <section class="card">
      <div class="filters">
        <select v-model="filterStatus" @change="refresh">
          <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <select v-model="filterRole" @change="refresh">
          <option value="">全部视角</option>
          <option value="reported">我提交的</option>
          <option value="assigned">指派给我的</option>
        </select>
        <button @click="refresh" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button>
        <span class="total">共 {{ total }} 条</span>
      </div>

      <table v-if="bugs.length">
        <thead>
          <tr>
            <th>ID</th><th>标题</th><th>级别</th><th>状态</th>
            <th>提交人</th><th>负责人</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="bug in bugs" :key="bug.id">
            <td>{{ bug.id }}</td>
            <td class="title-cell" :title="bug.description">{{ bug.title }}</td>
            <td><span class="badge" :class="severityClass[bug.severity]">{{ bug.severity }}</span></td>
            <td>{{ statusLabel[bug.status] ?? bug.status }}</td>
            <td>{{ bug.reporter_name }}</td>
            <td>{{ bug.assignee_name }}</td>
            <td class="actions">
              <button
                v-for="action in availableActions(bug)"
                :key="action.status"
                class="action-btn"
                @click="changeStatus(bug.id, action.status)"
              >{{ action.label }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="!loading" class="empty">暂无 Bug 记录</p>
    </section>
  </div>
</template>

<style scoped>
.bug-view { max-width: 960px; margin: 0 auto; padding: 16px; color: var(--text); }
.bug-view h1 { color: var(--text); }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.card h2 { color: var(--text); font-size: 16px; margin: 0 0 12px; }
.bug-form { display: grid; gap: 8px; }
.bug-form input, .bug-form select, .bug-form textarea {
  padding: 8px 10px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
}
.bug-form input::placeholder, .bug-form textarea::placeholder { color: var(--muted); }
.bug-form select option { background: var(--bg-soft); color: var(--text); }
.bug-form input:focus, .bug-form select:focus, .bug-form textarea:focus {
  outline: none;
  border-color: var(--primary);
}
.bug-form button {
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}
.bug-form button:disabled { opacity: 0.6; cursor: not-allowed; }
.filters { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.filters select, .filters button {
  padding: 6px 10px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  cursor: pointer;
}
.filters select option { background: var(--bg-soft); color: var(--text); }
.filters button:hover { border-color: var(--primary); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px; border-bottom: 1px solid var(--border); text-align: left; font-size: 14px; color: var(--text); }
th { color: var(--muted); font-weight: 600; }
.title-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; color: #fff; font-weight: 600; }
.sev-critical { background: #dc2626; }
.sev-major { background: #ea580c; }
.sev-minor { background: #2563eb; }
.sev-trivial { background: #6b7280; }
.actions { display: flex; gap: 4px; flex-wrap: wrap; }
.action-btn {
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}
.action-btn:hover { border-color: var(--primary); background: rgba(43, 161, 255, 0.14); }
.error { color: var(--danger); }
.empty { color: var(--muted); text-align: center; }
.total { color: var(--muted); font-size: 13px; }
</style>
