/**
 * DeepSeek Harness Cordis plugin for MindSlice.
 *
 * Plain Node.js ESM with zero external npm dependencies so it runs directly inside
 * DeepSeek Harness Desktop/Web/CLI without TypeScript compilation or pnpm build scripts.
 */

import { execFile, execFileSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export const name = 'mindslice'
export const inject = ['skills', 'systemPrompt', 'agents']

const SKILL_RANK = 600
const HOOK_TIMEOUT_MS = 58_000
const MCP_STARTUP_TIMEOUT_MS = 60_000
const PROBE_PY = 'import sys; print(sys.executable)'

const PASSTHROUGH_ENV = [
  'DSH_HOME',
  'DSH_PROFILE_DIR',
  'MINDSLICE_WORKSPACE',
  'MINDSLICE_PLUGIN_ISOLATE',
  'MINDSLICE_PLUGIN_ENGINE_DIR',
  'MINDSLICE_PLUGIN_WHEEL',
  'MINDSLICE_PLUGIN_STAGE_WRITES',
  'MINDSLICE_PLUGIN_OPTION_WORKSPACE',
]

function cleanEnvValue(value) {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed && !trimmed.includes('${') ? trimmed : undefined
}

function resolveDshHome() {
  return cleanEnvValue(process.env.DSH_HOME) ?? path.join(os.homedir(), '.dsh')
}

export function resolvePluginDataDir(ctx) {
  const explicit = cleanEnvValue(process.env.PLUGIN_DATA) ?? cleanEnvValue(process.env.MINDSLICE_PLUGIN_DATA)
  if (explicit) return explicit
  const profileDir = ctx?.get?.('profileContext')?.dir ?? cleanEnvValue(process.env.DSH_PROFILE_DIR)
  if (profileDir) return path.join(profileDir, 'plugin_data', 'mindslice')
  const desktopProfile = path.join(resolveDshHome(), 'profiles', 'desktop')
  if (existsSync(desktopProfile)) return path.join(desktopProfile, 'plugin_data', 'mindslice')
  return path.join(os.homedir(), '.cache', 'mindslice-plugin', 'deepseek-harness')
}

export function findPythonExecutable() {
  const candidates = process.platform === 'win32'
    ? ['py', 'python3', 'python']
    : ['python3', 'python']
  for (const candidate of candidates) {
    try {
      const out = execFileSync(candidate, ['-c', PROBE_PY], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 5000,
      }).trim()
      if (out && existsSync(out)) return out
    } catch {
      // Try next candidate (avoids Windows Store python3.exe stub or missing launchers).
    }
  }
  return undefined
}

function mcpCommandSpec(pluginRoot, pythonExe) {
  if (pythonExe) {
    return {
      command: pythonExe,
      args: [path.join(pluginRoot, 'adapter', 'entry.py'), 'mcp'],
    }
  }
  const launcher = process.platform === 'win32' ? 'mcp.cmd' : 'mcp'
  return {
    command: path.join(pluginRoot, 'adapter', launcher),
    args: [],
  }
}

export function buildChildEnv(pluginRoot, pluginData, config = {}) {
  const env = {
    PLUGIN_ROOT: pluginRoot,
    PLUGIN_DATA: pluginData,
    MINDSLICE_PLUGIN_DATA: pluginData,
  }
  for (const key of PASSTHROUGH_ENV) {
    const val = cleanEnvValue(process.env[key])
    if (val !== undefined) env[key] = val
  }
  if (typeof config.workspace === 'string' && config.workspace.trim()) {
    env.MINDSLICE_PLUGIN_OPTION_WORKSPACE = config.workspace.trim()
  }
  if (typeof config.stageWrites === 'boolean') {
    env.MINDSLICE_PLUGIN_STAGE_WRITES = config.stageWrites ? 'true' : 'false'
  }
  return env
}

function parseSkillMarkdown(raw) {
  const normalized = raw.replace(/\r\n/g, '\n')
  const match = normalized.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
  if (!match) return { meta: {}, body: normalized }
  const meta = {}
  for (const line of match[1].split('\n')) {
    const idx = line.indexOf(':')
    if (idx <= 0) continue
    const key = line.slice(0, idx).trim()
    let val = line.slice(idx + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    meta[key] = val
  }
  return { meta, body: match[2].trimStart() }
}

function createSkillProvider(pluginRoot) {
  const skillsDir = path.join(pluginRoot, 'skills')
  const byName = new Map()
  let entries = []
  try {
    entries = readdirSync(skillsDir, { withFileTypes: true })
  } catch {
    entries = []
  }
  const candidates = []
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const skillDir = path.join(skillsDir, entry.name)
    const skillFile = path.join(skillDir, 'SKILL.md')
    if (!existsSync(skillFile)) continue
    const raw = readFileSync(skillFile, 'utf8')
    const { meta } = parseSkillMarkdown(raw)
    const skillName = meta.name || entry.name
    const candidate = {
      name: skillName,
      description: meta.description || `MindSlice ${skillName} skill`,
      invocation: { modelInvocable: true, userInvocable: true },
      provider: 'mindslice',
      source: 'bundled',
      resourceBase: { kind: 'directory', path: skillDir },
      rank: SKILL_RANK,
      locator: skillFile,
      path: skillFile,
    }
    candidates.push(candidate)
    byName.set(skillName, { candidate, skillFile })
  }
  candidates.sort((a, b) => a.name.localeCompare(b.name))

  return {
    name: 'mindslice',
    list: async () => candidates,
    async get(candidate) {
      const record = byName.get(candidate.name)
      const file = record ? record.skillFile : candidate.locator
      const { body } = parseSkillMarkdown(readFileSync(file, 'utf8'))
      return {
        name: candidate.name,
        description: candidate.description,
        invocation: candidate.invocation,
        provider: candidate.provider,
        source: candidate.source,
        resourceBase: candidate.resourceBase,
        path: file,
        content: body,
      }
    },
  }
}

function countCompactions(session, tracker) {
  if (!session || typeof session.seq !== 'number' || typeof session.eventAt !== 'function') {
    return 0
  }
  const prevSeq = tracker?.seq ?? 0
  let count = tracker?.count ?? 0
  if (session.seq < prevSeq) {
    count = 0
  }
  const start = session.seq < prevSeq ? 0 : prevSeq
  for (let seq = start; seq < session.seq; seq += 1) {
    const ev = session.eventAt(seq)
    if (ev && ev.type === 'compaction/summary') count += 1
  }
  if (tracker) {
    tracker.seq = session.seq
    tracker.count = count
  }
  return count
}

async function runHookScript(pluginRoot, childEnv, pythonExe, sessionId, signal) {
  const hookPy = path.join(pluginRoot, 'adapter', 'hook.py')
  const payload = JSON.stringify({ session_id: sessionId, hook_event_name: 'SessionStart' })

  const runWith = async (cmd, args) => {
    const child = execFileAsync(cmd, args, {
      cwd: pluginRoot,
      env: { ...process.env, ...childEnv },
      timeout: HOOK_TIMEOUT_MS,
      maxBuffer: 4 * 1024 * 1024,
      signal,
    })
    child.child.stdin?.end(payload)
    return child
  }

  let stdout = ''
  if (pythonExe) {
    ({ stdout } = await runWith(pythonExe, [hookPy]))
  } else {
    const candidates = process.platform === 'win32' ? ['py', 'python3', 'python'] : ['python3', 'python']
    let lastErr
    for (const cmd of candidates) {
      try {
        ({ stdout } = await runWith(cmd, [hookPy]))
        lastErr = undefined
        break
      } catch (err) {
        lastErr = err
      }
    }
    if (lastErr) {
      return {
        sections: [
          `[MindSlice plugin could not start] Python 3.12+ is required (${lastErr.message}). `
          + 'Tell the user MindSlice memory is unavailable in this session and why.',
        ],
        cliBin: undefined,
      }
    }
  }

  const trimmed = stdout.trim()
  if (!trimmed) return { sections: [], cliBin: undefined }
  try {
    const parsed = JSON.parse(trimmed)
    return {
      sections: Array.isArray(parsed.systemPromptSections) ? parsed.systemPromptSections.filter(Boolean) : [],
      cliBin: typeof parsed.cliBin === 'string' ? parsed.cliBin : undefined,
    }
  } catch {
    return { sections: [trimmed], cliBin: undefined }
  }
}

export function apply(ctx, config = {}) {
  const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const pluginData = resolvePluginDataDir(ctx)
  const pythonExe = findPythonExecutable()
  const childEnv = buildChildEnv(pluginRoot, pluginData, config)

  const defaultCli = path.join(pluginData, 'bin', process.platform === 'win32' ? 'mindslice.cmd' : 'mindslice')
  let latestCliBin = existsSync(defaultCli)
    ? defaultCli
    : path.join(pluginRoot, 'bin', process.platform === 'win32' ? 'mindslice.cmd' : 'mindslice')

  // 1. Register MindSlice stdio MCP server through mcpManager (disposed automatically with this plugin).
  ctx.inject(['mcpManager'], (c) => {
    const mcp = mcpCommandSpec(pluginRoot, pythonExe)
    c.mcpManager.register('mindslice', {
      transport: 'stdio',
      command: mcp.command,
      args: mcp.args,
      cwd: pluginRoot,
      env: childEnv,
      startupTimeoutMs: MCP_STARTUP_TIMEOUT_MS,
    })
  })

  // 2. Register native MindSlice skills (mindslice-setup, mindslice-review, mindslice-slice-maintainer).
  ctx.skills.registerProvider(() => createSkillProvider(pluginRoot))

  // 3. Optionally expose DSH_MINDSLICE_BIN to bash/pwsh tools.
  ctx.inject(['shellEnv'], (c) => {
    c.shellEnv.register({
      name: 'mindslice',
      variables: {
        DSH_MINDSLICE_BIN: { description: 'Path to the MindSlice plugin CLI launcher.' },
      },
      resolve: () => ({ DSH_MINDSLICE_BIN: latestCliBin }),
    })
  })

  // 4. Deliver standing memory into system-prompt/assemble, cached per (sessionId, compactionCount).
  const memoryCache = new Map() // sessionId -> { compactions, text, tracker }
  const inFlight = new Map() // `${sessionId}:${compactions}` -> Promise<string>

  async function loadMemory(sessionId, compactions, signal) {
    if (childEnv.MINDSLICE_PLUGIN_ISOLATE === '1') return ''
    const cached = memoryCache.get(sessionId)
    if (cached && cached.compactions === compactions) return cached.text
    const key = `${sessionId}:${compactions}`
    if (inFlight.has(key)) return inFlight.get(key)

    const job = (async () => {
      try {
        const res = await runHookScript(pluginRoot, childEnv, pythonExe, sessionId, signal)
        if (res.cliBin) latestCliBin = res.cliBin
        const text = res.sections.join('\n\n')
        const prevTracker = memoryCache.get(sessionId)?.tracker ?? { seq: 0, count: compactions }
        memoryCache.set(sessionId, { compactions, text, tracker: prevTracker })
        return text
      } catch (err) {
        if (signal?.aborted) throw err
        ctx.logger?.warn?.(`mindslice: failed to load standing memory: ${String(err)}`)
        return '[MindSlice standing memory could not be delivered] Before you reply, call '
          + 'mcp__mindslice__manifest(include_always=true) and tell the user the plugin hit a delivery error.'
      } finally {
        inFlight.delete(key)
      }
    })()

    inFlight.set(key, job)
    return job
  }

  ctx.on('agent/created', async ({ agent, signal }) => {
    const sessionId = agent?.session?.header?.id
    if (!sessionId) return
    const tracker = { seq: 0, count: 0 }
    const compactions = countCompactions(agent.session, tracker)
    memoryCache.set(sessionId, { compactions: -1, text: '', tracker })
    await loadMemory(sessionId, compactions, signal)
  })

  ctx.on('agent/disposed', ({ agent }) => {
    const sessionId = agent?.session?.header?.id
    if (sessionId) memoryCache.delete(sessionId)
  })

  ctx.on('system-prompt/assemble', async (assembly, context, next) => {
    const out = await next()
    if (childEnv.MINDSLICE_PLUGIN_ISOLATE === '1') return out
    const agent = context?.agent
    const sessionId = agent?.session?.header?.id ?? 'default'
    let tracker = memoryCache.get(sessionId)?.tracker
    if (!tracker) {
      tracker = { seq: 0, count: 0 }
    }
    const compactions = countCompactions(agent?.session, tracker)
    const text = await loadMemory(sessionId, compactions, context?.signal)
    if (!text) return out
    return {
      ...out,
      sections: [
        ...out.sections,
        { name: 'mindslice:standing-memory', text, interpolate: false },
      ],
    }
  })

  ctx.effect(() => () => {
    memoryCache.clear()
    inFlight.clear()
  }, 'mindslice:cache')
}
