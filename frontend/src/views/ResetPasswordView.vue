<script setup>
import { ref } from 'vue'; import { useRoute } from 'vue-router'; import { api } from '../api'
const route=useRoute(), password=ref(''), error=ref(''), done=ref(false), busy=ref(false)
async function submit(){busy.value=true;error.value='';try{await api.auth.reset(route.query.token||'',password.value);done.value=true}catch(e){error.value=e.message}finally{busy.value=false}}
</script>
<template><main class="center-page"><section class="panel panel-pad reset"><h1>设置新密码</h1><p class="muted">至少 10 位，同时包含字母和数字。</p><div v-if="done" class="notice">密码已重置。<router-link to="/login">返回登录</router-link></div><form v-else @submit.prevent="submit"><div class="field"><label>新密码</label><input class="input" type="password" v-model="password" minlength="10" required/></div><div v-if="error" class="error-box">{{error}}</div><button class="btn primary" :disabled="busy">确认重置</button></form></section></main></template>
<style scoped>.center-page{min-height:100vh;display:grid;place-items:center;padding:20px}.reset{width:min(100%,420px)}.reset h1{margin:0}.reset form{display:grid;gap:16px;margin-top:24px}.reset .btn{width:100%}.notice{background:#e9f4ee;padding:14px;border-radius:6px}.notice a{color:var(--green);font-weight:700}</style>
