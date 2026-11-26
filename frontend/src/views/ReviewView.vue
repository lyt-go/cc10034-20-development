<template>
  <section class="page" data-module="review_package">
    <header class="page-head">
      <div>
        <h2>结果复核包</h2>
        <p class="page-desc">
          为差分查询执行重拿当时证据：锁定执行时刻的参数版本，把结果、参数、费用三联绑定核对；
          参数轮换后不以新参数顶替旧结果，迟到的原执行参数证据只归入已打开的复核申请。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh-all" type="button" @click="reloadAll">刷新证据包</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">复核包</span>
        <strong class="stat-value">{{ packages.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可复核（三联通过）</span>
        <strong class="stat-value">{{ eligibleCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待补证</span>
        <strong class="stat-value">{{ waitingCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已提交复核</span>
        <strong class="stat-value">{{ submittedCount }}</strong>
      </article>
    </div>

    <p v-if="message" class="page-desc" :class="messageKind" data-testid="review-message">{{ message }}</p>

    <h3 class="section-title">差分查询执行</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>查询编号</th>
          <th>执行时间</th>
          <th>参数版本</th>
          <th>配置引用</th>
          <th>费用回执</th>
          <th>当前资格</th>
          <th>复核操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="query in executedQueries" :key="String(query.id)" :data-testid="`query-row-${query.id}`">
          <td>{{ query['查询编号'] }}</td>
          <td>{{ query['执行时间'] }}</td>
          <td>{{ query['参数版本'] || '—' }}</td>
          <td>{{ query['配置引用'] || '引用已丢失' }}</td>
          <td>{{ query['费用回执'] || '—' }}</td>
          <td>
            <span :class="badgeClass(eligibilityOf(Number(query.id)))">
              {{ eligibilityOf(Number(query.id))?.eligible ? '可复核' : '不可复核' }}
            </span>
          </td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`build-${query.id}`"
              @click="onBuild(Number(query.id), false)"
            >
              结果复核包
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`reexecute-${query.id}`"
              @click="onBuild(Number(query.id), true)"
            >
              重新执行
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`open-request-${query.id}`"
              @click="onOpenRequest(Number(query.id))"
            >
              打开复核
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">证据包详情</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>复核包回执</th>
          <th>查询</th>
          <th>状态</th>
          <th>资格</th>
          <th>构建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="pkg in packages" :key="String(pkg.id)" :data-testid="`package-row-${pkg.id}`">
          <td>{{ pkg.receipt_no }}<span v-if="pkg.reexecuted" class="tag">重新执行</span></td>
          <td>{{ pkg.query_no }}</td>
          <td>{{ pkg.status }}</td>
          <td>
            <span :class="badgeClass(pkg.evaluation)">{{ pkg.evaluation.eligible ? '可复核' : '不可复核' }}</span>
          </td>
          <td>{{ pkg.created_at }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`detail-${pkg.id}`" @click="onDetail(pkg.id)">
              证据包详情
            </button>
          </td>
        </tr>
        <tr v-if="!packages.length">
          <td colspan="6" class="empty-state">暂无复核包，请先在上方为查询执行构建结果复核包</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">复核待办</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>申请编号</th>
          <th>查询</th>
          <th>状态</th>
          <th>补证回执</th>
          <th>不可复核原因</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="req in requests" :key="String(req.id)" :data-testid="`request-row-${req.id}`">
          <td>{{ req.request_no }}</td>
          <td>{{ req.query_no }}</td>
          <td>
            <span :class="req.status === '已提交' ? 'badge ok' : req.status === '待补证' ? 'badge bad' : 'badge warn'">
              {{ req.status }}
            </span>
          </td>
          <td>{{ req.supplement_evidence_no || '—' }}</td>
          <td>{{ req.block_reasons.length ? req.block_reasons.join('；') : '—' }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`submit-request-${req.id}`"
              :disabled="req.status === '已提交'"
              @click="onSubmitRequest(req.id)"
            >
              提交复核
            </button>
          </td>
        </tr>
        <tr v-if="!requests.length">
          <td colspan="6" class="empty-state">暂无复核待办</td>
        </tr>
      </tbody>
    </table>

    <div v-if="detail" class="modal-backdrop" data-testid="detail-modal" @click.self="detail = null">
      <div class="modal wide">
        <h3>证据包详情 {{ detail.receipt_no }}</h3>
        <p class="page-desc">
          查询 {{ detail.query_no }} ｜ 状态 {{ detail.status }} ｜ 构建于 {{ detail.created_at }}
          <span v-if="detail.superseded_at"> ｜ 替代于 {{ detail.superseded_at }}</span>
        </p>

        <div class="check-grid">
          <article v-for="(check, key) in detail.evaluation.checks" :key="key" class="check-card" :data-testid="`check-${key}`">
            <strong :class="check.ok ? 'ok-text' : 'bad-text'">{{ checkTitle(key) }}：{{ check.ok ? '通过' : '不通过' }}</strong>
            <p>{{ check.detail }}</p>
            <p v-if="check.source">证据来源：{{ sourceText(check.source) }}</p>
          </article>
        </div>
        <p v-if="!detail.evaluation.eligible" class="bad-text" data-testid="detail-reasons">
          不可复核原因：{{ detail.evaluation.reasons.join('；') }}
        </p>
        <p class="page-desc">
          执行声明参数版本 {{ detail.evaluation.claimed_version || '—' }} ｜
          当前生效版本 {{ detail.evaluation.current_effective_version || '—' }} ｜
          锁定指纹 {{ detail.evaluation.locked_fingerprint || '—' }}
        </p>

        <h4 class="section-title">参数证据（含迟到补证与不可采信留痕）</h4>
        <table class="data-table compact">
          <thead>
            <tr><th>证据回执</th><th>参数版本</th><th>采信</th><th>核对说明</th><th>到达时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="ev in detail.evidence ?? []" :key="String(ev.id)" :data-testid="`evidence-row-${ev.id}`">
              <td>{{ ev.evidence_no }}</td>
              <td>{{ ev.param_version }}</td>
              <td><span :class="ev.valid ? 'badge ok' : 'badge bad'">{{ ev.valid ? '采信' : '不采信' }}</span></td>
              <td>{{ ev.match_detail }}</td>
              <td>{{ ev.received_at }}</td>
            </tr>
            <tr v-if="!(detail.evidence ?? []).length">
              <td colspan="5" class="empty-state">该执行暂无参数证据</td>
            </tr>
          </tbody>
        </table>

        <div class="evidence-form" data-testid="evidence-form">
          <h4 class="section-title">登记迟到的原执行参数证据</h4>
          <div class="filter-bar">
            <label class="filter-item">
              <span>参数版本</span>
              <select v-model="evidenceForm.param_version" data-testid="evidence-version">
                <option value="" disabled>选择参数版本</option>
                <option v-for="ver in paramVersions" :key="ver.version" :value="ver.version">
                  {{ ver.version }}（{{ ver.status }}）
                </option>
              </select>
            </label>
            <label class="filter-item">
              <span>证据来源</span>
              <input v-model="evidenceForm.source" data-testid="evidence-source" placeholder="如：外部归档通道补传" />
            </label>
          </div>
          <p class="page-desc">
            选择版本后自动带出该版本台账参数快照，仅当指纹与台账规范指纹一致且版本与执行声明相符时才采信。
          </p>
          <div class="page-actions">
            <button class="btn" type="button" @click="detail = null">关闭</button>
            <button class="btn primary" type="button" data-testid="register-evidence" @click="onRegisterEvidence">
              登记证据
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  buildReviewPackage,
  fetchParamVersions,
  fetchReviewPackages,
  fetchReviewRequests,
  openReviewRequest,
  registerEvidence,
  submitReviewRequest,
  fetchReviewPackage,
} from '@/api/review-service'
import { listEntries } from '@/api/backend-service'
import type {
  EntryRow,
  PackageEvaluation,
  ParamVersion,
  ReviewPackage,
  ReviewRequest,
} from '@/data/types'

const executedQueries = ref<EntryRow[]>([])
const packages = ref<ReviewPackage[]>([])
const requests = ref<ReviewRequest[]>([])
const paramVersions = ref<ParamVersion[]>([])
const detail = ref<ReviewPackage | null>(null)
const message = ref('')
const messageKind = ref('page-desc')

const evidenceForm = reactive({ param_version: '', source: '' })

const eligibleCount = computed(
  () => packages.value.filter((pkg) => pkg.evaluation.eligible && pkg.status === '有效').length,
)
const waitingCount = computed(() => requests.value.filter((req) => req.status === '待补证').length)
const submittedCount = computed(() => requests.value.filter((req) => req.status === '已提交').length)

function badgeClass(evaluation?: PackageEvaluation): string {
  return evaluation?.eligible ? 'badge ok' : 'badge bad'
}

function checkTitle(key: string): string {
  return { input: '原输入/结果', fee: '费用', params: '参数' }[key] ?? key
}

function sourceText(source: string): string {
  return { direct: '直接配置引用', evidence: '原执行参数证据', none: '无有效来源' }[source] ?? source
}

function eligibilityOf(queryId: number): PackageEvaluation | undefined {
  return packages.value.find((pkg) => pkg.query_id === queryId && pkg.status === '有效')?.evaluation
}

function setNotice(text: string, ok = true): void {
  message.value = text
  messageKind.value = ok ? 'ok-text' : 'bad-text'
}

async function reloadAll(): Promise<void> {
  try {
    const [queryPage, packagePage, requestPage, versionPage] = await Promise.all([
      listEntries('differential_sql'),
      fetchReviewPackages(),
      fetchReviewRequests(),
      fetchParamVersions(),
    ])
    executedQueries.value = queryPage.items.filter((row) => row.status === '已执行')
    packages.value = packagePage.items
    requests.value = requestPage.items
    paramVersions.value = versionPage.items
  } catch (error) {
    setNotice(error instanceof Error ? error.message : '复核台数据读取失败', false)
  }
}

async function onBuild(queryId: number, reexecute: boolean): Promise<void> {
  const result = await buildReviewPackage(queryId, reexecute)
  setNotice(result.message, result.ok)
  await reloadAll()
  if (result.entry) await onDetail(result.entry.id)
}

async function onDetail(packageId: number): Promise<void> {
  const result = await fetchReviewPackage(packageId)
  if (result.entry) {
    detail.value = result.entry
    evidenceForm.param_version = result.entry.evaluation.claimed_version
    evidenceForm.source = ''
  } else {
    setNotice(result.message, false)
  }
}

async function onOpenRequest(queryId: number): Promise<void> {
  const result = await openReviewRequest(queryId)
  setNotice(result.message, result.ok)
  await reloadAll()
}

async function onSubmitRequest(requestId: number): Promise<void> {
  const result = await submitReviewRequest(requestId)
  setNotice(result.message, result.ok)
  await reloadAll()
  if (detail.value) await onDetail(detail.value.id)
}

async function onRegisterEvidence(): Promise<void> {
  if (!detail.value) return
  const version = paramVersions.value.find((item) => item.version === evidenceForm.param_version)
  if (!version) {
    setNotice('请先选择参数版本', false)
    return
  }
  const result = await registerEvidence({
    query_id: detail.value.query_id,
    param_version: version.version,
    snapshot: version.params,
    source: evidenceForm.source || '外部补证通道',
  })
  setNotice(result.message, result.ok)
  await reloadAll()
  // 刷新已打开的详情页：核对补证是否归入本次复核。
  const refreshed = await fetchReviewPackage(detail.value.id)
  if (refreshed.entry) detail.value = refreshed.entry
}

onMounted(reloadAll)
</script>
