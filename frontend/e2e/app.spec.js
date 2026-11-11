import { expect, test } from '@playwright/test'

async function createAccount(request, projectName) {
  const email = `ui-${projectName}-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
  const password = 'SecurePass123'
  const registration = await request.post('/api/auth/register', {
    data: { email, password, display_name: 'UI Check' },
  })
  expect(registration.status()).toBe(201)
  const verificationUrl = (await registration.json()).verification_url
  expect(verificationUrl).toBeTruthy()
  const token = new URL(verificationUrl).searchParams.get('token')
  const verification = await request.post('/api/auth/verify', { data: { token } })
  expect(verification.ok()).toBe(true)
  return { email, password }
}

async function removeAccount(request, credentials) {
  const login = await request.post('/api/auth/login', { data: credentials })
  if (!login.ok()) return
  const { access_token: token } = await login.json()
  await request.delete('/api/me', { headers: { Authorization: `Bearer ${token}` } })
}

test('login surface is responsive and has no horizontal overflow', async ({ page }, testInfo) => {
  await page.goto('/login')
  await expect(page.getByText('BartenderAI', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '登录' }).last()).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
  await page.screenshot({ path: testInfo.outputPath('login.png'), fullPage: true })
})

test('authenticated workbench keeps every module reachable', async ({ page, request }, testInfo) => {
  const credentials = await createAccount(request, testInfo.project.name)
  try {
    await page.goto('/login')
    await page.getByLabel('邮箱').fill(credentials.email)
    await page.getByLabel('密码').fill(credentials.password)
    await page.getByRole('button', { name: '登录' }).last().click()
    await expect(page.getByRole('heading', { name: 'AI 调酒台' })).toBeVisible()
    const atmosphere = page.locator('.mixology-atmosphere canvas')
    await expect(atmosphere).toBeVisible()
    await expect.poll(() => atmosphere.getAttribute('data-animation-ready')).toBe('true')
    await expect(atmosphere).toHaveAttribute('data-theme', 'conversation')
    expect(Number(await atmosphere.getAttribute('data-doodle-count'))).toBeGreaterThan(10)
    await page.locator('a[href="/explore"]:visible').click()
    await expect(page.getByRole('heading', { name: '配方探索' })).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-theme', 'citrus')
    const atmosphereInteractions = Number(await atmosphere.getAttribute('data-interaction-count'))
    await page.mouse.click(1200, 30)
    await expect.poll(async () => Number(await atmosphere.getAttribute('data-interaction-count'))).toBeGreaterThan(atmosphereInteractions)
    const filterMotions = Number(await atmosphere.getAttribute('data-business-interaction-count'))
    await page.getByRole('button', { name: '偏甜', exact: true }).click()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'filter')
    await expect.poll(async () => Number(await atmosphere.getAttribute('data-business-interaction-count'))).toBeGreaterThan(filterMotions)
    await page.reload()
    await expect(page.getByRole('heading', { name: '配方探索' })).toBeVisible()
    await expect(page.locator('.recipe-tile').first()).toBeVisible()
    const motionSignatures = await page.locator('.recipe-tile').evaluateAll(
      (tiles) => tiles.slice(0, 12).map((tile) => ({
        profile: tile.dataset.motionProfile,
        signature: tile.dataset.motionSignature,
        animation: getComputedStyle(tile.querySelector('.motion-field i')).animationName,
      })),
    )
    expect(motionSignatures.length).toBeGreaterThanOrEqual(8)
    expect(new Set(motionSignatures.map((item) => item.signature)).size).toBeGreaterThanOrEqual(4)
    expect(motionSignatures.every((item) => item.profile && item.animation !== 'none')).toBe(true)
    const firstMotionTile = page.locator('.recipe-tile').first()
    await expect(firstMotionTile).toHaveAttribute('data-interaction-count', '0')
    await firstMotionTile.dispatchEvent('pointerdown', { pointerType: 'mouse' })
    await expect(firstMotionTile).toHaveAttribute('data-interaction-count', '1')
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'recipe-motion')
    await firstMotionTile.dispatchEvent('pointerdown', { pointerType: 'touch', clientX: 10, clientY: 10 })
    await firstMotionTile.dispatchEvent('pointerup', { pointerType: 'touch', clientX: 45, clientY: 10 })
    await expect(firstMotionTile).toHaveAttribute('data-interaction-count', '1')
    await firstMotionTile.dispatchEvent('pointerdown', { pointerType: 'touch', clientX: 10, clientY: 10 })
    await firstMotionTile.dispatchEvent('pointerup', { pointerType: 'touch', clientX: 13, clientY: 12 })
    await expect(firstMotionTile).toHaveAttribute('data-interaction-count', '2')
    await page.waitForTimeout(450)
    await page.screenshot({ path: testInfo.outputPath('explore-recipe-motion.png'), fullPage: true })
    await page.getByRole('button', { name: /预览 .* 的 3D 粒子酒体/ }).first().click()
    const preview = page.getByRole('dialog', { name: /3D 粒子预览/ })
    await expect(preview).toBeVisible()
    const previewCanvas = preview.locator('.particle-scene canvas')
    await expect(previewCanvas).toBeVisible()
    await expect.poll(() => previewCanvas.getAttribute('data-scene-ready')).toBe('true')
    await page.screenshot({ path: testInfo.outputPath('explore-3d-preview.png'), fullPage: true })
    await page.getByRole('button', { name: '关闭 3D 预览' }).click()
    await expect(preview).toHaveCount(0)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
    expect(overflow).toBe(false)
    if (testInfo.project.name === 'mobile-360') {
      for (const href of ['/chat', '/explore', '/studio', '/lab', '/inventory', '/moments', '/vision', '/me']) {
        await expect(page.locator(`.bottom-nav a[href="${href}"]`)).toHaveCount(1)
      }
    }
    await page.screenshot({ path: testInfo.outputPath('explore.png'), fullPage: true })

    await page.goto('/studio')
    const agentCanvas = page.locator('.agent-mixing-stage canvas')
    await expect(agentCanvas).toBeVisible()
    await expect.poll(() => agentCanvas.getAttribute('data-animation-ready')).toBe('true')
    await expect(agentCanvas).toHaveAttribute('data-interaction', 'pointer-flow')
    const personaButtons = page.locator('.persona-grid button')
    await expect(personaButtons).toHaveCount(4)
    const topologies = []
    for (let index = 0; index < 4; index += 1) {
      await personaButtons.nth(index).click()
      await expect.poll(() => agentCanvas.getAttribute('data-topology')).not.toBe(topologies.at(-1) || '')
      topologies.push(await agentCanvas.getAttribute('data-topology'))
    }
    expect(new Set(topologies).size).toBe(4)
    await personaButtons.first().click()
    const beforeBriefSignature = await agentCanvas.getAttribute('data-brief-signature')
    await page.locator('.creation-form textarea').fill('低甜，草本香，入口轻盈但保留酒感')
    await expect.poll(() => agentCanvas.getAttribute('data-brief-signature')).not.toBe(beforeBriefSignature)
    const beforePalette = await agentCanvas.getAttribute('data-palette')
    await page.locator('.base-options').getByText('金酒', { exact: true }).click()
    await expect.poll(() => agentCanvas.getAttribute('data-palette')).not.toBe(beforePalette)
    const stagePixels = await agentCanvas.evaluate((element) => {
      const context = element.getContext('2d')
      const pixels = context.getImageData(0, 0, element.width, element.height).data
      let lit = 0
      for (let index = 0; index < pixels.length; index += Math.max(4, Math.floor(pixels.length / 12000 / 4) * 4)) {
        if (pixels[index] + pixels[index + 1] + pixels[index + 2] > 70) lit += 1
      }
      return { lit, width: element.width, height: element.height }
    })
    expect(stagePixels.lit).toBeGreaterThan(100)
    expect(stagePixels.width).toBeGreaterThan(250)
    expect(stagePixels.height).toBeGreaterThan(180)
    await agentCanvas.scrollIntoViewIfNeeded()
    const stageBox = await agentCanvas.boundingBox()
    await page.mouse.click(stageBox.x + stageBox.width * .48, stageBox.y + stageBox.height * .58)
    await expect(agentCanvas).toHaveAttribute('data-interaction-count', '1')
    await expect(agentCanvas).not.toHaveAttribute('data-focused-agent', 'none')
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'agent')
    await agentCanvas.focus()
    await page.keyboard.press('ArrowRight')
    await expect(agentCanvas).not.toHaveAttribute('data-focused-agent', 'none')
    await page.keyboard.press('Enter')
    await expect(agentCanvas).toHaveAttribute('data-interaction-count', '2')
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
    await page.screenshot({ path: testInfo.outputPath('studio-agent-field.png'), fullPage: true })

    await page.goto('/inventory')
    await expect(page.getByRole('heading', { name: '我的酒柜' })).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-theme', 'shelf')
    await page.getByRole('button', { name: '+ 金酒', exact: true }).click()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'shelf-in')
    await expect(page.locator('.stock-chip', { hasText: '金酒' })).toBeVisible()

    await page.goto('/moments')
    await expect(page.getByRole('heading', { name: '场景酒单' })).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-theme', 'celebration')
    await page.locator('.theme').first().click()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'theme-open')
    const themeDetail = page.locator('.theme-detail')
    await expect(themeDetail).toBeVisible()
    await expect.poll(async () => Number(await themeDetail.getAttribute('data-resolved-count'))).toBeGreaterThan(0)
    expect(await themeDetail.locator('.recipe-orbit i').first().evaluate((element) => getComputedStyle(element).animationName)).not.toBe('none')
    await page.getByRole('button', { name: /预览 .* 的粒子酒体/ }).first().click()
    const momentPreview = page.getByRole('dialog', { name: /粒子酒体预览/ })
    await expect(momentPreview).toBeVisible()
    const momentCanvas = momentPreview.locator('.particle-scene canvas')
    await expect(momentCanvas).toBeVisible()
    await expect.poll(() => momentCanvas.getAttribute('data-scene-ready')).toBe('true')
    await page.getByRole('button', { name: '关闭粒子预览' }).click()
    await expect(momentPreview).toHaveCount(0)
    await page.getByRole('button', { name: '生成风味方向' }).click()
    await expect(page.locator('.context-result')).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'context-ready')
    const guestField = page.locator('.guest-field')
    await expect(guestField).toHaveAttribute('data-headcount', '4')
    expect(await guestField.locator('span').first().evaluate((element) => getComputedStyle(element).animationName)).not.toBe('none')
    await page.getByRole('button', { name: '增加一位宾客' }).click()
    await expect(guestField).toHaveAttribute('data-headcount', '5')
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'guest-count')
    await page.getByRole('button', { name: '计算备料' }).click()
    await expect(page.locator('.banquet article').first()).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'banquet-ready')
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
    await page.waitForTimeout(550)
    await page.screenshot({ path: testInfo.outputPath('moments-theme-motion.png'), fullPage: true })

    await page.goto('/vision')
    await expect(page.getByRole('heading', { name: '拍照识方' })).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-theme', 'focus')
    await page.locator('input[type="file"]').setInputFiles('src/assets/auth-cocktail.jpg')
    await expect(page.locator('.drop.filled img')).toBeVisible()
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'focus')
    await page.screenshot({ path: testInfo.outputPath('vision-scan-motion.png'), fullPage: true })

    await page.goto('/me')
    await expect(page.getByRole('heading', { name: '收藏与个人中心' })).toBeVisible()
    await page.getByRole('button', { name: '口味画像' }).click()
    const flavorBloom = page.locator('.flavor-bloom canvas')
    await expect(flavorBloom).toBeVisible()
    await expect.poll(() => flavorBloom.getAttribute('data-animation-ready')).toBe('true')
    await expect(flavorBloom).toHaveAttribute('data-petals', '6')
    await page.locator('.range input').first().fill('8')
    await expect(flavorBloom).toHaveAttribute('data-values', /^8-/)
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'profile')
    await flavorBloom.click({ position: { x: 120, y: 90 } })
    await expect(flavorBloom).toHaveAttribute('data-interaction-count', '1')
    await page.screenshot({ path: testInfo.outputPath('profile-flavor-bloom.png'), fullPage: true })
  } finally {
    await removeAccount(request, credentials)
  }
})

test('recipe detail renders an interactive nonblank particle cocktail', async ({ page, request }, testInfo) => {
  const credentials = await createAccount(request, `particles-${testInfo.project.name}`)
  try {
    await page.goto('/login')
    await page.getByLabel('邮箱').fill(credentials.email)
    await page.getByLabel('密码').fill(credentials.password)
    await page.getByRole('button', { name: '登录' }).last().click()
    await expect(page.getByRole('heading', { name: 'AI 调酒台' })).toBeVisible()

    await page.goto('/recipes/11007')
    const canvas = page.locator('.particle-scene canvas')
    await expect(canvas).toBeVisible()
    await expect.poll(() => canvas.getAttribute('data-scene-ready')).toBe('true')
    const pixels = await canvas.evaluate((element) => ({
      lit: Number(element.dataset.litPixels),
      colors: Number(element.dataset.colorBuckets),
      width: element.width,
      height: element.height,
    }))
    expect(pixels.lit).toBeGreaterThan(30)
    expect(pixels.colors).toBeGreaterThan(3)
    expect(pixels.width).toBeGreaterThan(250)
    expect(pixels.height).toBeGreaterThan(200)
    const particleCount = Number(await canvas.getAttribute('data-particle-count'))
    if (testInfo.project.name === 'mobile-360') expect(particleCount).toBeLessThanOrEqual(900)
    if (testInfo.project.name === 'tablet-768') expect(particleCount).toBeLessThanOrEqual(1500)
    if (testInfo.project.name === 'desktop-1440') expect(particleCount).toBeGreaterThanOrEqual(2000)
    await expect(canvas).toHaveAttribute('data-technique', /shake|stir|build|layer|blend|balanced/)
    await expect(canvas).toHaveAttribute('data-glass-kind', /cone|coupe|flute|hurricane|wine|highball|rocks|shot/)
    await expect(canvas).toHaveAttribute('data-carbonated', /true|false/)
    await expect(canvas).toHaveAttribute('data-garnish-kind', /citrus|herb|cherry|none/)
    expect((await canvas.getAttribute('data-palette-signature')).length).toBeGreaterThan(5)
    await expect(canvas).toHaveAttribute('data-interaction', /^drag-/)

    const box = await canvas.boundingBox()
    await page.mouse.move(box.x + box.width * .3, box.y + box.height * .55)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * .72, box.y + box.height * .38, { steps: 7 })
    await page.mouse.up()
    await expect(canvas).toHaveAttribute('data-interaction-count', '1')

    const firstIngredient = page.locator('.ingredients li').first()
    await firstIngredient.hover()
    await expect(canvas).toHaveAttribute('data-highlight-ingredient', '0')
    await firstIngredient.click()
    await expect(canvas).toHaveAttribute('data-prepared-count', '1')
    await page.locator('.steps .step-number').first().click()
    await expect(canvas).toHaveAttribute('data-active-step', '1')
    await expect(canvas).toHaveAttribute('data-step-motion', /shake|stir|build|layer|blend|balanced|pour|strain|garnish/)
    await page.locator('.steps .step-number').nth(1).click()
    await expect(canvas).toHaveAttribute('data-active-step', '2')
    const timer = page.locator('.mix-timer')
    await expect(timer).toBeVisible()
    await expect(timer).toHaveAttribute('data-running', 'false')
    await timer.getByRole('button', { name: '开始计时' }).click()
    await expect(timer).toHaveAttribute('data-running', 'true')
    await expect(canvas).toHaveAttribute('data-timer-running', 'true')
    await expect.poll(async () => Number(await timer.getAttribute('data-progress'))).toBeGreaterThan(0)
    await expect.poll(async () => Number(await canvas.getAttribute('data-timer-progress'))).toBeGreaterThan(0)
    const atmosphere = page.locator('.mixology-atmosphere canvas')
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'timer')
    await page.waitForTimeout(650)
    await page.screenshot({ path: testInfo.outputPath('recipe-timer-linked-running.png'), fullPage: true })
    await timer.getByRole('button', { name: '暂停计时' }).click()
    await expect(timer).toHaveAttribute('data-running', 'false')
    await expect(canvas).toHaveAttribute('data-timer-running', 'false')
    await expect(atmosphere).toHaveAttribute('data-last-business-event', 'timer-pause')
    await timer.getByRole('button', { name: '重置计时' }).click()
    await expect(timer).toHaveAttribute('data-progress', '0.000')
    await expect(canvas).toHaveAttribute('data-timer-progress', '0.000')
    await timer.scrollIntoViewIfNeeded()
    await page.waitForTimeout(180)
    await page.getByRole('tab', { name: '成品图' }).click()
    await expect(canvas).toHaveCount(0)
    await page.getByRole('tab', { name: '粒子酒体' }).click()
    await expect(page.locator('.particle-scene canvas')).toBeVisible()
    if (testInfo.project.name === 'desktop-1440') {
      const identities = [], motions = [], interactions = [], palettes = []
      for (const id of ['17222', '13501', '12572']) {
        await page.goto(`/recipes/${id}`)
        const candidate = page.locator('.particle-scene canvas')
        await expect(candidate).toBeVisible()
        await expect.poll(() => candidate.getAttribute('data-scene-ready')).toBe('true')
        identities.push(await candidate.getAttribute('data-visual-profile'))
        motions.push(await candidate.getAttribute('data-motion-signature'))
        interactions.push(await candidate.getAttribute('data-interaction'))
        palettes.push(await candidate.getAttribute('data-palette-signature'))
        expect(Number(await candidate.getAttribute('data-lit-pixels'))).toBeGreaterThan(30)
        expect(Number(await candidate.getAttribute('data-color-buckets'))).toBeGreaterThan(3)
        await page.screenshot({ path: testInfo.outputPath(`particle-identity-${id}.png`) })
      }
      expect(new Set(identities).size).toBe(3)
      expect(new Set(motions).size).toBe(3)
      expect(new Set(interactions).size).toBe(3)
      expect(new Set(palettes).size).toBeGreaterThanOrEqual(2)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(overflow).toBe(false)
    await page.screenshot({ path: testInfo.outputPath('recipe-particles.png'), fullPage: true })
  } finally {
    await removeAccount(request, credentials)
  }
})

test('chat understands contextual counts, streams, and resolves ordinal follow-ups', async ({ page, request }, testInfo) => {
  const credentials = await createAccount(request, `chat-${testInfo.project.name}`)
  try {
    await page.addInitScript(() => {
      const nativeFetch = window.fetch.bind(window)
      window.__chatPartialEvents = 0
      window.fetch = async (...args) => {
        const response = await nativeFetch(...args)
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || ''
        if (url.includes('/messages/stream') && response.body) {
          response.clone().text().then((body) => {
            window.__chatPartialEvents += (body.match(/\"type\"\s*:\s*\"partial\"/g) || []).length
          })
        }
        return response
      }
    })
    await page.goto('/login')
    await page.getByLabel('邮箱').fill(credentials.email)
    await page.getByLabel('密码').fill(credentials.password)
    await page.getByRole('button', { name: '登录' }).last().click()
    await expect(page.getByRole('heading', { name: 'AI 调酒台' })).toBeVisible()
    const chatParticles = page.locator('.chat-particle-field canvas')
    await expect(chatParticles).toBeVisible()
    await expect.poll(async () => Number(await chatParticles.getAttribute('data-particle-count'))).toBeGreaterThanOrEqual(68)
    await expect(chatParticles).toHaveAttribute('data-phase', 'idle')
    await page.locator('.composer textarea').fill('甜的，不酸')
    await page.locator('.composer .send').click()
    await expect(chatParticles).toHaveAttribute('data-active', 'true')
    const assistant = page.locator('.message.assistant').last()
    await expect(assistant).toContainText('分步调制', { timeout: 20_000 })
    await expect(chatParticles).toHaveAttribute('data-active', 'false')
    await expect(chatParticles).toHaveAttribute('data-phase', 'done')
    await expect(assistant).not.toContainText('Connection error')
    expect(await assistant.locator('.recipe-guide ol li').count()).toBeGreaterThanOrEqual(4)
    const userBox = await page.locator('.message.user').last().boundingBox()
    const assistantBox = await assistant.boundingBox()
    expect(userBox.x).toBeGreaterThan(assistantBox.x)

    const firstRecipeLink = await assistant.locator('.recipe-answer-head a').getAttribute('href')
    await page.locator('.composer textarea').fill('给我多推荐五个')
    await page.locator('.composer .send').click()
    const recommendations = page.locator('.message.assistant').last()
    await expect(recommendations.locator('.recommendation-card')).toHaveCount(5, { timeout: 20_000 })
    await expect(recommendations).not.toContainText('暂时没有')
    await expect(recommendations).not.toContainText('Connection error')
    const recommendationNames = await recommendations.locator('.recommendation-card h3').allInnerTexts()
    const recommendationLinks = await recommendations.locator('.recommendation-card').evaluateAll(
      (cards) => cards.map((card) => card.getAttribute('href')),
    )
    expect(new Set(recommendationNames).size).toBe(5)
    expect(new Set(recommendationLinks).size).toBe(5)
    expect(recommendationLinks).not.toContain(firstRecipeLink)
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(hasHorizontalOverflow).toBe(false)
    await recommendations.scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('chat-recommendations.png') })
    await page.locator('.composer textarea').fill('第二个怎么调')
    await page.locator('.composer .send').click()
    const ordinalAnswer = page.locator('.message.assistant').last()
    await expect(ordinalAnswer.locator('.recipe-answer-head strong')).toHaveText(recommendationNames[1], { timeout: 20_000 })
    expect(await ordinalAnswer.locator('.recipe-guide ol li').count()).toBeGreaterThanOrEqual(4)
    await expect(ordinalAnswer).not.toContainText('Connection error')
  } finally {
    await removeAccount(request, credentials)
  }
})

test('recipe guide, lab, and collaborative creation are user-facing', async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440', 'live creation runs once on desktop')
  const credentials = await createAccount(request, 'product-ai')
  try {
    await page.goto('/login')
    await page.getByLabel('邮箱').fill(credentials.email)
    await page.getByLabel('密码').fill(credentials.password)
    await page.getByRole('button', { name: '登录' }).last().click()
    await expect(page.getByRole('heading', { name: 'AI 调酒台' })).toBeVisible()

    await page.goto('/explore')
    await page.locator('.search-wrap input').fill('Margarita')
    await expect(page.locator('.recipe-tile').first()).toBeVisible()
    await page.locator('.recipe-tile h3 a').first().click()
    await expect(page.getByRole('heading', { name: '跟着步骤调制' })).toBeVisible()
    expect(await page.locator('.steps ol li').count()).toBeGreaterThanOrEqual(4)
    await expect(page.locator('.equipment')).toBeVisible()

    await page.goto('/lab')
    await expect(page.getByRole('heading', { name: '配方实验室' })).toBeVisible()
    await expect(page.locator('pre')).toHaveCount(0)
    const labArchive = page.locator('.archive-strip')
    const archiveImage = labArchive.locator('img')
    await expect(archiveImage).toBeVisible()
    expect(await archiveImage.evaluate((image) => image.naturalWidth)).toBeGreaterThan(500)
    const archiveTransform = await archiveImage.evaluate((image) => getComputedStyle(image).transform)
    const archiveBox = await labArchive.boundingBox()
    await page.mouse.move(archiveBox.x + archiveBox.width * .86, archiveBox.y + archiveBox.height * .74)
    await expect.poll(() => archiveImage.evaluate((image) => getComputedStyle(image).transform)).not.toBe(archiveTransform)
    await page.getByRole('button', { name: '解构重组' }).click()
    await expect(page.locator('.mixology-atmosphere canvas')).toHaveAttribute('data-last-business-event', 'experiment')
    await page.screenshot({ path: testInfo.outputPath('lab-archive-motion.png'), fullPage: true })
    await page.setViewportSize({ width: 360, height: 800 })
    await expect(labArchive).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
    await page.screenshot({ path: testInfo.outputPath('lab-archive-mobile.png'), fullPage: true })
    await page.setViewportSize({ width: 1440, height: 1000 })

    await page.goto('/studio')
    await page.locator('.creation-form textarea').fill('夏夜慢饮，低甜，柑橘和草本香，不要太酸')
    await page.locator('.base-options').getByText('金酒', { exact: true }).click()
    await page.getByRole('button', { name: '开始创作' }).click()
    await expect(page.locator('.result-card')).toBeVisible({ timeout: 45_000 })
    const liveAgentCanvas = page.locator('.agent-mixing-stage canvas')
    await expect.poll(async () => Number(await liveAgentCanvas.getAttribute('data-stage-count'))).toBeGreaterThanOrEqual(5)
    await expect.poll(async () => Number(await liveAgentCanvas.getAttribute('data-progress'))).toBeGreaterThanOrEqual(4)
    await expect(page.locator('.collaboration')).toContainText('需求分析')
    await expect(page.locator('.collaboration')).toContainText('参考检索')
    await expect(page.locator('.collaboration')).toContainText(/(独立吧台审校完成|规则复核完成)/)
    expect(await page.locator('.result-card .steps li').count()).toBeGreaterThanOrEqual(4)
    await expect(page.locator('.result-card')).not.toContainText('undefined')
    await expect(page.locator('pre')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('studio-live-collaboration.png'), fullPage: true })
    const creationName = await page.locator('.result-card h2').innerText()
    await expect(page.locator('.creation-item').first()).toBeVisible()
    await page.locator('.creation-item').first().click()
    await expect(page).toHaveURL(/\/studio\/creations\/\d+$/)
    await expect(page.locator('.creation-hero h1')).toHaveText(creationName)
    const creationCanvas = page.locator('.creation-visual canvas')
    await expect(creationCanvas).toBeVisible()
    await expect.poll(() => creationCanvas.getAttribute('data-scene-ready')).toBe('true')
    const creationPixels = await creationCanvas.evaluate((element) => ({
      lit: Number(element.dataset.litPixels),
      colors: Number(element.dataset.colorBuckets),
    }))
    expect(creationPixels.lit).toBeGreaterThan(30)
    expect(creationPixels.colors).toBeGreaterThan(3)
    expect(await page.locator('.materials li').count()).toBeGreaterThanOrEqual(2)
    expect(await page.locator('.mixing li').count()).toBeGreaterThanOrEqual(4)
    await expect(page.locator('.agent-panel')).toContainText('需求分析')
    await expect(page.locator('.agent-panel')).toContainText('出品复核')
    await page.screenshot({ path: testInfo.outputPath('creation-detail.png'), fullPage: true })
    await page.setViewportSize({ width: 360, height: 800 })
    const creationOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(creationOverflow).toBe(false)
    await expect(page.locator('.materials')).toBeVisible()
    await expect(page.locator('.agent-panel')).toBeVisible()
    await expect(page.locator('.creation-visual canvas')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('creation-detail-mobile.png'), fullPage: true })
  } finally {
    await removeAccount(request, credentials)
  }
})
