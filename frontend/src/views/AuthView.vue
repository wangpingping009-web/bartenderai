<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { GlassWater, LoaderCircle } from 'lucide-vue-next'

const auth = useAuthStore(), router = useRouter(), route = useRoute()
const mode = ref('login'), email = ref(''), password = ref(''), displayName = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), actionUrl = ref('')
async function submit() {
  busy.value = true; error.value = ''; notice.value = ''; actionUrl.value = ''
  try {
    if (mode.value === 'login') { await auth.login({ email: email.value, password: password.value }); router.replace(route.query.next || '/chat') }
    else if (mode.value === 'register') { const data = await api.auth.register({ email: email.value, password: password.value, display_name: displayName.value }); notice.value = data.message; actionUrl.value = data.verification_url || '' }
    else { const data = await api.auth.forgot(email.value); notice.value = data.message; actionUrl.value = data.reset_url || '' }
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <main class="auth-page">
    <div class="auth-image" aria-hidden="true"></div>
    <section class="auth-form">
      <div class="auth-inner">
        <div class="auth-brand"><span><GlassWater :size="23" /></span>BartenderAI</div>
        <div class="segmented auth-tabs" v-if="mode !== 'forgot'">
          <button :class="{active:mode==='login'}" @click="mode='login';error='';notice=''">登录</button>
          <button :class="{active:mode==='register'}" @click="mode='register';error='';notice=''">注册</button>
        </div>
        <h1>{{ mode === 'login' ? '回到你的吧台' : mode === 'register' ? '创建调酒档案' : '重置密码' }}</h1>
        <p>{{ mode === 'login' ? '继续管理酒柜、收藏与创作记录。' : mode === 'register' ? '邮箱验证后即可使用完整功能。' : '输入注册邮箱，我们会发送重置链接。' }}</p>
        <form @submit.prevent="submit" class="auth-fields">
          <div class="field" v-if="mode==='register'"><label for="display-name">显示名称</label><input id="display-name" v-model="displayName" class="input" maxlength="80" autocomplete="name" /></div>
          <div class="field"><label for="account-email">邮箱</label><input id="account-email" v-model="email" class="input" type="email" required autocomplete="email" /></div>
          <div class="field" v-if="mode!=='forgot'"><label for="account-password">密码</label><input id="account-password" v-model="password" class="input" type="password" required :minlength="mode==='register'?10:1" :autocomplete="mode==='login'?'current-password':'new-password'" /><small v-if="mode==='register'">至少 10 位，同时包含字母和数字</small></div>
          <div v-if="error" class="error-box">{{ error }}</div><div v-if="notice" class="notice">{{ notice }} <a v-if="actionUrl" :href="actionUrl">立即继续</a></div>
          <button class="btn primary auth-submit" :disabled="busy"><LoaderCircle v-if="busy" :size="17" class="spin" />{{ mode==='login'?'登录':mode==='register'?'注册并验证':'发送重置邮件' }}</button>
        </form>
        <button class="text-link" v-if="mode==='login'" @click="mode='forgot';error='';notice=''">忘记密码</button>
        <button class="text-link" v-if="mode==='forgot'" @click="mode='login';error='';notice=''">返回登录</button>
      </div>
    </section>
  </main>
</template>
<style scoped>
.auth-page{min-height:100vh;display:grid;grid-template-columns:minmax(320px,1fr) minmax(420px,520px);background:#151b18}.auth-image{background:url('../assets/auth-cocktail.jpg') center/cover no-repeat;min-height:100vh;position:relative}.auth-image:after{content:"";position:absolute;inset:0;background:rgba(13,18,15,.24)}.auth-form{background:#f8f7f3;display:grid;place-items:center;padding:34px}.auth-inner{width:min(100%,380px)}.auth-brand{display:flex;align-items:center;gap:10px;font-size:19px;font-weight:800;margin-bottom:55px}.auth-brand span{display:grid;place-items:center;width:36px;height:36px;background:#d99235;border-radius:6px}.auth-tabs{margin-bottom:24px}.auth-tabs button{min-width:90px}.auth-inner h1{font-size:30px;margin:0}.auth-inner>p{color:var(--muted);margin:9px 0 25px}.auth-fields{display:grid;gap:16px}.field small{color:var(--muted);font-size:11px}.auth-submit{width:100%;margin-top:4px}.notice{background:#e9f4ee;color:#205d44;border:1px solid #bfd9cb;padding:11px;border-radius:6px;font-size:13px}.notice a{color:#174b37;font-weight:700}.text-link{display:block;border:0;background:none;color:var(--green);margin:18px auto 0}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:760px){.auth-page{grid-template-columns:1fr;background:#f8f7f3}.auth-image{display:none}.auth-form{padding:24px;min-height:100vh}.auth-brand{margin-bottom:38px}}
</style>
