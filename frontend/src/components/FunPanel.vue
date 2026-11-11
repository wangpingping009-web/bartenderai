<template>
  <div class="panel">
    <!-- 每日一酒 + 挑战 -->
    <section class="block">
      <div class="block-title">🍀 今日玩法</div>
      <div class="daily" @click="loadDaily">
        <div class="daily-name">{{ daily?.recipe?.name || '看看今天喝什么' }}</div>
        <div class="daily-sub" v-if="daily">{{ daily.recipe.category }} · {{ daily.recipe.ingredients_text }}</div>
        <div class="daily-sub" v-else>点击刷新每日一酒（按日期确定，每天一杯）</div>
      </div>
      <div class="challenge" v-if="challenge">
        <div class="challenge-title">{{ challenge.title }}</div>
        <ol class="steps">
          <li v-for="s in challenge.steps" :key="s">{{ s }}</li>
        </ol>
      </div>
      <el-button size="small" @click="loadChallenge">换一道挑战</el-button>
    </section>

    <!-- 情境感知 -->
    <section class="block">
      <div class="block-title">🌤️ 情境感知推荐</div>
      <div class="ctx-row">
        <el-select v-model="ctx.time" size="small" placeholder="时间" clearable style="width: 90px">
          <el-option v-for="(v,k) in TIMES" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-model="ctx.weather" size="small" placeholder="天气" clearable style="width: 90px">
          <el-option v-for="(v,k) in WEATHERS" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-model="ctx.mood" size="small" placeholder="心情" clearable style="width: 100px">
          <el-option v-for="(v,k) in MOODS" :key="k" :label="v" :value="k" />
        </el-select>
        <el-button size="small" type="primary" @click="loadContext">感知</el-button>
      </div>
      <div v-if="ctxResult?.keywords?.length" class="ctx-result">
        <el-tag v-for="k in ctxResult.keywords" :key="k" size="small" type="success" effect="plain">{{ k }}</el-tag>
        <div class="ctx-why">{{ ctxResult.summary }}</div>
        <el-button size="small" class="ask" @click="askByContext">让调酒师按这个方向推荐</el-button>
      </div>
    </section>

    <!-- 零酒模式 -->
    <section class="block">
      <div class="block-title">🍹 零酒模式</div>
      <div class="ctx-row">
        <el-select v-model="mockSrc" size="small" filterable placeholder="选一杯想改造的酒" style="width: 180px">
          <el-option v-for="m in mocktails" :key="m.name" :label="m.name" :value="m.name" />
        </el-select>
        <el-button size="small" type="warning" :disabled="!mockSrc" @click="loadMocktail">改造成零酒精</el-button>
      </div>
      <div v-if="mocktail" class="mock">
        <div class="mock-name">{{ mocktail.mocktail_name }} <el-tag size="small" type="success">0% 酒精</el-tag></div>
        <div v-for="r in mocktail.replaced" :key="r.from" class="replaced">⬇ {{ r.from }} → <b>{{ r.to }}</b><em>{{ r.why }}</em></div>
        <div v-for="i in mocktail.ingredients" :key="i.name" class="ing">{{ i.name }} <em>{{ i.amount }}</em></div>
        <div class="note">{{ mocktail.note }}</div>
      </div>
    </section>

    <!-- 晚宴规划 -->
    <section class="block">
      <div class="block-title">🥂 晚宴规划</div>
      <div class="ctx-row">
        <el-select v-model="banquetNames" size="small" multiple filterable placeholder="选多杯酒" style="width: 200px">
          <el-option v-for="m in mocktails" :key="m.name" :label="m.name" :value="m.name" />
        </el-select>
        <el-input-number v-model="banquetCount" :min="1" size="small" />
        <el-button size="small" type="primary" :disabled="!banquetNames.length" @click="loadBanquet">规划</el-button>
      </div>
      <div v-if="banquet" class="banquet">
        <div v-for="c in banquet.cocktails" :key="c.name" class="b-card">
          <div class="b-name">{{ c.name }} <el-tag v-if="c.alcohol_free" size="small" type="success">零酒</el-tag></div>
          <div v-if="c.error" class="b-err">{{ c.error }}</div>
          <div v-else>
            <div v-for="i in c.ingredients" :key="i.name" class="ing">{{ i.name }} <em>{{ i.per_person }}ml/人 · {{ i.for_n }}ml/桌</em></div>
            <div class="b-alc" v-if="c.total_spirit_ml">🍸 纯酒精约 {{ c.total_spirit_ml }}ml（人均 {{ c.per_person_spirit_ml }}ml）</div>
            <div class="b-hint">{{ c.method_hint }}</div>
          </div>
        </div>
        <div class="tips"><div v-for="t in banquet.batch_tips" :key="t">📌 {{ t }}</div></div>
      </div>
    </section>

    <!-- 技能树 + 徽章 -->
    <section class="block">
      <div class="block-title">🏆 我的成长</div>
      <div v-if="progress" class="progress">
        <div class="lvl">Lv.{{ progress.level.level }} <b>{{ progress.level.name }}</b> {{ progress.level.emoji }}
          <span class="xp">XP {{ progress.xp }}<template v-if="progress.level.next_level"> · 距{{ progress.level.next_level }}还差{{ progress.level.xp_to_next }}</template></span>
        </div>
        <div class="badges">
          <div v-for="b in progress.badges" :key="b.id" class="badge" :class="{ earned: b.earned }">
            <span class="b-emoji">{{ b.emoji }}</span>
            <span class="b-name">{{ b.name }}</span>
            <span class="b-desc">{{ b.desc }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const props = defineProps({ username: { type: String, default: 'guest' } })
const emit = defineEmits(['ask'])

const TIMES = { morning: '清晨', afternoon: '午后', evening: '傍晚', night: '夜晚' }
const WEATHERS = { hot: '炎热', cold: '寒冷', rain: '下雨', windy: '多风' }
const MOODS = { happy: '开心', tired: '疲惫', stressed: '压力', sad: '低落', curious: '好奇' }

const daily = ref(null)
const challenge = ref(null)
const ctx = reactive({ time: '', weather: '', mood: '' })
const ctxResult = ref(null)
const mocktails = ref([])
const mockSrc = ref('')
const mocktail = ref(null)
const banquetNames = ref([])
const banquetCount = ref(4)
const banquet = ref(null)
const progress = ref(null)

async function loadDaily() { daily.value = await api.fun.daily(); api.fun.action('daily', props.username).catch(() => {}) }
async function loadChallenge() { challenge.value = await api.fun.challenge() }
async function loadContext() { ctxResult.value = await api.fun.context(ctx) }
function askByContext() {
  emit('ask', `我现在：${ctx.time && TIMES[ctx.time]}${ctx.weather && WEATHERS[ctx.weather]}${ctx.mood && MOODS[ctx.mood]}，心情${ctx.mood ? MOODS[ctx.mood] : '一般'}，帮我推荐 ${ctxResult.value.keywords.join('、')} 方向的鸡尾酒`)
}
async function loadMocktail() {
  mocktail.value = await api.fun.mocktail(mockSrc.value, props.username)
  api.fun.action('mocktail', props.username).catch(() => {})
}
async function loadBanquet() {
  banquet.value = await api.fun.banquet(banquetNames.value, banquetCount.value, false, props.username)
  api.fun.action('banquet', props.username).catch(() => {})
}

onMounted(async () => {
  loadDaily(); loadChallenge(); loadContext()
  try { mocktails.value = await api.fun.mocktails() } catch (_) { mocktails.value = [] }
  loadProgress()
})

async function loadProgress() {
  try { progress.value = await api.fun.progress(props.username) } catch (_) {}
}
</script>

<style scoped>
.panel { padding: 4px; }
.block { border: 1px solid #eee; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
.block-title { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.ctx-row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }

.daily { border: 1px dashed #5b8c5a; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; cursor: pointer; }
.daily-name { font-size: 14px; font-weight: 600; color: #5b8c5a; }
.daily-sub { font-size: 12px; color: #999; margin-top: 3px; }
.challenge { background: #f7f4ec; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
.challenge-title { font-size: 13px; font-weight: 600; color: #8a6d3b; }
.steps { margin: 6px 0 0 18px; font-size: 12px; color: #666; }

.ctx-result { margin-top: 6px; }
.ctx-why { font-size: 12px; color: #666; margin: 4px 0; }
.ask { width: 100%; margin-top: 4px; }

.mock-name { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.replaced { font-size: 12px; color: #5b8c5a; margin: 3px 0; }
.replaced em, .ing em { font-style: normal; color: #999; }
.ing { font-size: 12px; color: #444; margin: 2px 0; }
.note { font-size: 12px; color: #8a6d3b; background: #fdf8e8; border-radius: 6px; padding: 6px 8px; margin-top: 8px; }

.b-card { border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
.b-name { font-size: 13px; font-weight: 600; }
.b-err { font-size: 12px; color: #c45656; }
.b-alc { font-size: 12px; color: #5b8c5a; margin-top: 4px; }
.b-hint { font-size: 12px; color: #999; margin-top: 4px; }
.tips { font-size: 12px; color: #8a6d3b; background: #fdf8e8; border-radius: 6px; padding: 6px 8px; }

.progress .lvl { font-size: 14px; font-weight: 600; }
.progress .xp { font-size: 12px; color: #999; font-weight: 400; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.badge { border: 1px solid #eee; border-radius: 8px; padding: 6px 8px; font-size: 11px; width: 96px; text-align: center; opacity: 0.45; filter: grayscale(1); }
.badge.earned { opacity: 1; filter: none; border-color: #5b8c5a; background: #f2f8f2; }
.b-emoji { font-size: 18px; display: block; }
.b-name { font-weight: 600; display: block; margin: 2px 0; }
.b-desc { color: #999; display: block; }
</style>
