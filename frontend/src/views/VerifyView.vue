<script setup>
import { onMounted, ref } from 'vue'; import { useRoute } from 'vue-router'; import { api } from '../api'; import { CircleCheck, CircleX, LoaderCircle } from 'lucide-vue-next'
const route=useRoute(), state=ref('loading'), message=ref('正在验证邮箱...')
onMounted(async()=>{try{await api.auth.verify(route.query.token||'');state.value='ok';message.value='邮箱验证成功，现在可以登录。'}catch(e){state.value='error';message.value=e.message}})
</script>
<template><main class="center-page"><section class="panel panel-pad verify"><LoaderCircle v-if="state==='loading'" :size="38" class="spin"/><CircleCheck v-else-if="state==='ok'" :size="42" class="ok"/><CircleX v-else :size="42" class="bad"/><h1>{{ message }}</h1><router-link class="btn primary" to="/login">前往登录</router-link></section></main></template>
<style scoped>.center-page{min-height:100vh;display:grid;place-items:center;padding:20px}.verify{text-align:center;max-width:430px}.verify h1{font-size:20px;margin:18px 0}.ok{color:var(--green)}.bad{color:var(--red)}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>
