<script setup>
import { computed } from 'vue'
const props=defineProps({flavor:{type:Object,default:()=>({})}})
const labels=[['甜','sweet'],['酸','sour'],['苦','bitter'],['烈','strong'],['醇','body'],['香','aroma']]
const points=computed(()=>labels.map(([,key],i)=>{const angle=-Math.PI/2+i*Math.PI/3,r=42*Math.min(10,Number(props.flavor[key]||0))/10;return `${50+Math.cos(angle)*r},${50+Math.sin(angle)*r}`}).join(' '))
const axes=labels.map((item,i)=>{const angle=-Math.PI/2+i*Math.PI/3;return {label:item[0],x:50+Math.cos(angle)*46,y:50+Math.sin(angle)*46,lx:50+Math.cos(angle)*54,ly:50+Math.sin(angle)*54}})
</script>
<template><svg viewBox="-8 -8 116 116" role="img" aria-label="风味雷达图"><polygon v-for="n in 4" :key="n" :points="axes.map(a=>`${50+(a.x-50)*n/4},${50+(a.y-50)*n/4}`).join(' ')" class="web"/><line v-for="a in axes" :key="a.label" x1="50" y1="50" :x2="a.x" :y2="a.y" class="axis"/><polygon :points="points" class="value"/><text v-for="a in axes" :key="a.label+'t'" :x="a.lx" :y="a.ly" text-anchor="middle" dominant-baseline="middle">{{a.label}}</text></svg></template>
<style scoped>svg{width:100%;max-width:280px}.web,.axis{fill:none;stroke:#dce1dd;stroke-width:.7}.value{fill:rgba(201,121,24,.25);stroke:#c97918;stroke-width:1.5}text{font-size:7px;fill:#68706c}</style>
