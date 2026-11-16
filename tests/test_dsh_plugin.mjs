import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '..')
const PLUGIN_ROOT = path.join(REPO, 'plugins', 'deepseek-harness')
const PLUGIN_URL = pathToFileURL(path.join(PLUGIN_ROOT, 'adapter', 'plugin.js')).href

const ENGINE_DIR = process.env.MINDSLICE_PLUGIN_ENGINE_DIR
assert.ok(ENGINE_DIR, 'MINDSLICE_PLUGIN_ENGINE_DIR must be set for test_dsh_plugin.mjs')

function findPy() {
  for (const cand of process.platform === 'win32' ? ['py', 'python3', 'python'] : ['python3', 'python']) {
    try {
      const exe = execFileSync(cand, ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim()
      if (exe) return exe
    } catch {
      // next
    }
  }
  throw new Error('python not found')
}

function initWorkspace(wsDir, cardId, phrase) {
  const py = findPy()
  const script = `
import sys
sys.path.insert(0, ${JSON.stringify(ENGINE_DIR)})
from pathlib import Path
from mindslice import Workspace
ws = Workspace.init(Path(${JSON.stringify(wsDir)}))
ws.write(${JSON.stringify(cardId)}, op="create", content=${JSON.stringify(`Standing phrase: ${phrase}.`)}, summary="phrase", title="Phrase", load="always", stage=False, reason="test")
ws.close()
`
  execFileSync(py, ['-c', script], { encoding: 'utf8' })
}

function addAlwaysCard(wsDir, cardId, phrase) {
  const py = findPy()
  const script = `
import sys
sys.path.insert(0, ${JSON.stringify(ENGINE_DIR)})
from pathlib import Path
from mindslice import Workspace
with Workspace(Path(${JSON.stringify(wsDir)})) as ws:
    ws.write(${JSON.stringify(cardId)}, op="create", content=${JSON.stringify(`Second phrase: ${phrase}.`)}, summary="phrase2", title="Phrase 2", load="always", stage=False, reason="test")
`
  execFileSync(py, ['-c', script], { encoding: 'utf8' })
}

function createMockCtx(profileDir) {
  const events = new Map()
  const effects = []
  let mcpRegistration = null
  let skillProvider = null
  let shellEnvContributor = null

  const ctx = {
    get(service) {
      if (service === 'profileContext') return { name: 'desktop', dir: profileDir }
      return undefined
    },
    inject(deps, fn) {
      const scoped = {
        ...ctx,
        mcpManager: {
          register(name, entry) {
            mcpRegistration = { name, entry }
            return () => { mcpRegistration = null }
          },
        },
        shellEnv: {
          register(contributor) {
            shellEnvContributor = contributor
            return () => { shellEnvContributor = null }
          },
        },
      }
      if (deps.includes('mcpManager') || deps.includes('shellEnv')) {
        fn(scoped)
      }
    },
    skills: {
      registerProvider(factory) {
        skillProvider = factory({ signal: new AbortController().signal, invalidate() {} })
        return () => { skillProvider = null }
      },
    },
    on(event, handler) {
      const list = events.get(event) ?? []
      list.push(handler)
      events.set(event, list)
      return () => {}
    },
    effect(fn) {
      const dispose = fn()
      if (typeof dispose === 'function') effects.push(dispose)
      return () => {}
    },
    logger: { warn() {}, info() {} },
  }

  async function emit(event, ...args) {
    for (const h of events.get(event) ?? []) {
      await h(...args)
    }
  }

  async function assemble(agent) {
    const handlers = events.get('system-prompt/assemble') ?? []
    let idx = 0
    const context = { agent, signal: new AbortController().signal }
    const base = { sections: [], contexts: [], variables: {} }
    async function next() {
      if (idx >= handlers.length) return base
      const fn = handlers[idx++]
      return fn(base, context, next)
    }
    return next()
  }

  return {
    ctx,
    emit,
    assemble,
    getMcp: () => mcpRegistration,
    getSkills: () => skillProvider,
    getShellEnv: () => shellEnvContributor,
    dispose: () => { for (const d of effects) d() },
  }
}

test('DeepSeek Harness Cordis plugin lifecycle, skills, compaction refresh, isolation, and MCP handshake', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mindslice-dsh-test-'))
  try {
    const profileDir = path.join(tmp, 'profile')
    const pluginData = path.join(profileDir, 'plugin_data', 'mindslice')
    const wsDir = path.join(tmp, 'ws')
    fs.mkdirSync(pluginData, { recursive: true })
    initWorkspace(wsDir, 'prefs/phrase', 'ALPHA-TANGO-9')
    fs.writeFileSync(path.join(pluginData, 'settings.json'), JSON.stringify({ workspace: wsDir }))

    const mod = await import(PLUGIN_URL)
    assert.equal(mod.name, 'mindslice')
    assert.deepEqual(mod.inject, ['skills', 'systemPrompt', 'agents'])

    const mock = createMockCtx(profileDir)
    mod.apply(mock.ctx, {})

    // 1. Skills provider
    const provider = mock.getSkills()
    assert.ok(provider)
    const listed = await provider.list()
    assert.deepEqual(listed.map((s) => s.name), ['mindslice-review', 'mindslice-setup', 'mindslice-slice-maintainer'])
    for (const item of listed) {
      assert.match(item.name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/)
      const def = await provider.get(item)
      assert.ok(def.content.length > 50)
      assert.ok(!def.content.startsWith('---'))
    }

    // 2. ShellEnv
    const se = mock.getShellEnv()
    assert.ok(se)
    const resolvedEnv = se.resolve({})
    assert.ok(resolvedEnv.DSH_MINDSLICE_BIN.includes('mindslice'))

    // 3. Standing memory on agent/created + caching + compaction refresh
    const log = []
    const session = {
      header: { id: 'dsh-sess-1' },
      get seq() { return log.length },
      eventAt(i) { return log[i] },
    }
    const agent = { id: 'dsh-sess-1', session }

    await mock.emit('agent/created', { agent, source: 'startup', signal: new AbortController().signal })
    const first = await mock.assemble(agent)
    const sec1 = first.sections.find((s) => s.name === 'mindslice:standing-memory')
    assert.ok(sec1)
    assert.equal(sec1.interpolate, false)
    assert.match(sec1.text, /ALPHA-TANGO-9/)

    // Add a second card: without compaction, cache preserves the session prefix
    addAlwaysCard(wsDir, 'prefs/second', 'BETA-SIERRA-2')
    const second = await mock.assemble(agent)
    const sec2 = second.sections.find((s) => s.name === 'mindslice:standing-memory')
    assert.equal(sec2.text, sec1.text)

    // Record compaction/summary: next assemble refreshes standing memory automatically
    log.push({ type: 'compaction/summary', seq: 0 })
    const third = await mock.assemble(agent)
    const sec3 = third.sections.find((s) => s.name === 'mindslice:standing-memory')
    assert.match(sec3.text, /ALPHA-TANGO-9/)
    assert.match(sec3.text, /BETA-SIERRA-2/)

    // 4. Registered MCP server starts and completes initialize + tools/list
    const mcp = mock.getMcp()
    assert.ok(mcp)
    assert.equal(mcp.name, 'mindslice')
    assert.equal(mcp.entry.transport, 'stdio')
    assert.equal(mcp.entry.env.PLUGIN_DATA, pluginData)
    const reqs = [
      { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'test', version: '1' } } },
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      { jsonrpc: '2.0', id: 2, method: 'tools/list' },
    ].map((x) => JSON.stringify(x)).join('\n') + '\n'
    const proc = spawnSync(mcp.entry.command, mcp.entry.args, {
      cwd: mcp.entry.cwd,
      env: { ...process.env, ...mcp.entry.env },
      input: reqs,
      encoding: 'utf8',
      timeout: 30000,
    })
    assert.equal(proc.status, 0, proc.stderr)
    const msgs = proc.stdout.trim().split('\n').map((l) => JSON.parse(l))
    const toolsResp = msgs.find((m) => m.id === 2)
    assert.deepEqual(toolsResp.result.tools.map((t) => t.name).sort(), ['manifest', 'read', 'search', 'write'])

    // 5. Isolation disables standing memory injection
    process.env.MINDSLICE_PLUGIN_ISOLATE = '1'
    try {
      const isoMock = createMockCtx(profileDir)
      mod.apply(isoMock.ctx, {})
      const isoAssembled = await isoMock.assemble(agent)
      assert.equal(isoAssembled.sections.length, 0)
      isoMock.dispose()
    } finally {
      delete process.env.MINDSLICE_PLUGIN_ISOLATE
    }

    mock.dispose()
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})
