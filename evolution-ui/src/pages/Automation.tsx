import { useCallback, useEffect, useRef, useState } from 'react'
import {
  automation,
  sessions,
  subscribeSSE,
  type HandoffItem,
  type OneShotResult,
  type TurnResult,
} from '../api'

interface TurnEntry {
  turn_num: number
  intent: string
  steps_total: number
  steps_ok: number
  cost_usd: number
  success: boolean
  error_msg: string | null
}

export default function Automation() {
  const [url, setUrl] = useState('')
  const [intent, setIntent] = useState('')
  const [headless, setHeadless] = useState(true)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionStatus, setSessionStatus] = useState<string | null>(null)
  const [turns, setTurns] = useState<TurnEntry[]>([])
  const [totalCost, setTotalCost] = useState(0)
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null)
  const [executing, setExecuting] = useState(false)
  const [pendingHandoffs, setPendingHandoffs] = useState<HandoffItem[]>([])
  const [handoffModalOpen, setHandoffModalOpen] = useState(false)
  const [activeHandoff, setActiveHandoff] = useState<HandoffItem | null>(null)
  const [handoffAction, setHandoffAction] = useState('')
  const [oneShotResult, setOneShotResult] = useState<OneShotResult | null>(null)

  const prevScreenshotUrl = useRef<string | null>(null)

  const refreshScreenshot = useCallback(async (sid: string) => {
    try {
      const blob = await sessions.screenshot(sid)
      const objectUrl = URL.createObjectURL(blob)
      if (prevScreenshotUrl.current) {
        URL.revokeObjectURL(prevScreenshotUrl.current)
      }
      prevScreenshotUrl.current = objectUrl
      setScreenshotUrl(objectUrl)
    } catch {
      // Screenshot may not be available yet
    }
  }, [])

  // SSE listener for session events
  useEffect(() => {
    const es = subscribeSSE((type, data) => {
      const d = data as Record<string, unknown>
      if (sessionId && d.session_id === sessionId) {
        if (type === 'session_turn_completed') {
          refreshScreenshot(sessionId)
        }
        if (type === 'handoff_requested') {
          const item = data as unknown as HandoffItem
          setPendingHandoffs((prev) => [...prev, item])
          setActiveHandoff(item)
          setHandoffModalOpen(true)
        }
        if (type === 'handoff_resolved') {
          const rid = d.request_id as string
          setPendingHandoffs((prev) => prev.filter((h) => h.request_id !== rid))
        }
        if (type === 'session_closed' || type === 'session_expired') {
          setSessionStatus(d.status as string ?? 'closed')
        }
      }
    })
    return () => es.close()
  }, [sessionId, refreshScreenshot])

  // Cleanup screenshot blob URL on unmount
  useEffect(() => {
    return () => {
      if (prevScreenshotUrl.current) {
        URL.revokeObjectURL(prevScreenshotUrl.current)
      }
    }
  }, [])

  const handleNewSession = async () => {
    setExecuting(true)
    setOneShotResult(null)
    try {
      const res = await sessions.create(url || undefined, headless)
      setSessionId(res.session_id)
      setSessionStatus(res.status)
      setTurns([])
      setTotalCost(0)
      setScreenshotUrl(null)
      setPendingHandoffs([])
    } catch (e) {
      console.error('Failed to create session:', e)
    } finally {
      setExecuting(false)
    }
  }

  const handleExecuteTurn = async () => {
    if (!sessionId || !intent.trim()) return
    setExecuting(true)
    setOneShotResult(null)
    try {
      const result: TurnResult = await sessions.turn(sessionId, intent.trim())
      const entry: TurnEntry = {
        turn_num: result.turn_num,
        intent: intent.trim(),
        steps_total: result.steps_total,
        steps_ok: result.steps_ok,
        cost_usd: result.cost_usd,
        success: result.success,
        error_msg: result.error_msg,
      }
      setTurns((prev) => [...prev, entry])
      setTotalCost((prev) => prev + result.cost_usd)
      setIntent('')

      // Refresh screenshot after turn
      await refreshScreenshot(sessionId)

      // Check for new handoffs
      if (result.pending_handoffs > 0) {
        const handoffs = await sessions.handoffs(sessionId)
        setPendingHandoffs(handoffs)
        if (handoffs.length > 0) {
          setActiveHandoff(handoffs[0])
          setHandoffModalOpen(true)
        }
      }
    } catch (e) {
      console.error('Turn failed:', e)
    } finally {
      setExecuting(false)
    }
  }

  const handleOneShotRun = async () => {
    if (!intent.trim()) return
    setExecuting(true)
    try {
      const result = await automation.run(intent.trim(), url || undefined, headless)
      setOneShotResult(result)
      setIntent('')
    } catch (e) {
      console.error('One-shot run failed:', e)
    } finally {
      setExecuting(false)
    }
  }

  const handleResolveHandoff = async () => {
    if (!sessionId || !activeHandoff || !handoffAction.trim()) return
    try {
      await sessions.resolveHandoff(sessionId, activeHandoff.request_id, handoffAction.trim())
      setPendingHandoffs((prev) => prev.filter((h) => h.request_id !== activeHandoff.request_id))
      setHandoffModalOpen(false)
      setActiveHandoff(null)
      setHandoffAction('')
    } catch (e) {
      console.error('Resolve handoff failed:', e)
    }
  }

  const handleCloseSession = async () => {
    if (!sessionId) return
    try {
      await sessions.close(sessionId)
      setSessionStatus('closed')
    } catch (e) {
      console.error('Close session failed:', e)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Automation</h1>
        <button
          onClick={handleNewSession}
          disabled={executing}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          New Session
        </button>
      </div>

      {/* Input controls */}
      <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4 space-y-3">
        <div className="flex gap-3 items-center">
          <label className="text-sm text-gray-400 w-12 shrink-0">URL</label>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <div className="flex items-center gap-4 text-sm text-gray-400">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                name="headless"
                checked={headless}
                onChange={() => setHeadless(true)}
                className="accent-indigo-500"
              />
              Headless
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                name="headless"
                checked={!headless}
                onChange={() => setHeadless(false)}
                className="accent-indigo-500"
              />
              Headful
            </label>
          </div>
        </div>
        <div className="flex gap-3 items-center">
          <label className="text-sm text-gray-400 w-12 shrink-0">Intent</label>
          <input
            type="text"
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && sessionId) handleExecuteTurn()
            }}
            placeholder="Describe what you want to do..."
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleExecuteTurn}
            disabled={executing || !sessionId || !intent.trim()}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
          >
            {executing ? 'Executing...' : 'Execute Turn'}
          </button>
          <button
            onClick={handleOneShotRun}
            disabled={executing || !intent.trim()}
            className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
          >
            One-Shot Run
          </button>
          {sessionId && sessionStatus === 'active' && (
            <button
              onClick={handleCloseSession}
              className="ml-auto bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded text-sm font-medium transition-colors"
            >
              Close Session
            </button>
          )}
        </div>
      </div>

      {/* Session info bar */}
      {sessionId && (
        <div className="flex items-center gap-4 bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-3 text-sm">
          <div>
            <span className="text-gray-500">Session:</span>{' '}
            <span className="font-mono text-gray-300">{sessionId}</span>
          </div>
          <SessionBadge status={sessionStatus ?? 'unknown'} />
          <span className="text-gray-500">
            Cost: <span className="text-gray-300">${totalCost.toFixed(4)}</span>
          </span>
          <span className="text-gray-500">
            Turns: <span className="text-gray-300">{turns.length}</span>
          </span>
          <span className={`px-2 py-0.5 rounded text-xs ${headless ? 'bg-gray-700 text-gray-400' : 'bg-blue-900/50 text-blue-400'}`}>
            {headless ? 'Headless' : 'Headful'}
          </span>
          {pendingHandoffs.length > 0 && (
            <span className="px-2 py-0.5 rounded text-xs bg-red-900/50 text-red-400">
              {pendingHandoffs.length} handoff(s)
            </span>
          )}
        </div>
      )}

      {/* One-shot result */}
      {oneShotResult && (
        <div className={`border rounded-lg p-4 space-y-2 ${oneShotResult.success ? 'bg-green-900/20 border-green-800' : 'bg-red-900/20 border-red-800'}`}>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">One-Shot Result</h3>
            <span className={`text-xs font-medium ${oneShotResult.success ? 'text-green-400' : 'text-red-400'}`}>
              {oneShotResult.success ? 'SUCCESS' : 'FAILED'}
            </span>
          </div>
          <div className="flex gap-4 text-xs text-gray-400">
            <span>Steps: {oneShotResult.steps_ok}/{oneShotResult.steps_total}</span>
            <span>Cost: ${oneShotResult.cost_usd.toFixed(4)}</span>
            <span>Tokens: {oneShotResult.tokens_used}</span>
            {oneShotResult.final_url && <span>URL: {oneShotResult.final_url}</span>}
          </div>
          {oneShotResult.error_msg && (
            <p className="text-xs text-red-300">{oneShotResult.error_msg}</p>
          )}
        </div>
      )}

      {/* Main content: turns + screenshot */}
      <div className="grid grid-cols-2 gap-6">
        {/* Turn history */}
        <div>
          <h2 className="text-lg font-semibold mb-3">Turn History</h2>
          {turns.length === 0 ? (
            <div className="bg-gray-800/50 rounded-lg p-6 text-center text-gray-500 text-sm">
              {sessionId ? 'No turns yet. Enter an intent and click Execute Turn.' : 'Create a session to get started.'}
            </div>
          ) : (
            <div className="space-y-2">
              {turns.map((t) => (
                <div key={t.turn_num} className="bg-gray-800/50 rounded p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-gray-400">#{t.turn_num}</span>
                    <span className={`text-xs font-medium ${t.success ? 'text-green-400' : 'text-red-400'}`}>
                      {t.success ? 'OK' : 'FAIL'}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300 mt-1">{t.intent}</p>
                  <div className="flex gap-3 mt-1 text-xs text-gray-500">
                    <span>{t.steps_ok}/{t.steps_total} steps</span>
                    <span>${t.cost_usd.toFixed(4)}</span>
                  </div>
                  {t.error_msg && (
                    <p className="text-xs text-red-400 mt-1">{t.error_msg}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Screenshot viewer */}
        <div>
          <h2 className="text-lg font-semibold mb-3">Screenshot</h2>
          <div className="bg-gray-800/50 rounded-lg overflow-hidden">
            {screenshotUrl ? (
              <img
                src={screenshotUrl}
                alt="Current page screenshot"
                className="w-full h-auto"
              />
            ) : (
              <div className="p-6 text-center text-gray-500 text-sm">
                Screenshot will appear here after a turn completes.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Handoff modal */}
      {handoffModalOpen && activeHandoff && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-lg w-full mx-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-orange-400">Human Handoff Required</h3>
              <button
                onClick={() => setHandoffModalOpen(false)}
                className="text-gray-500 hover:text-gray-300"
              >
                &times;
              </button>
            </div>
            <div className="space-y-2 text-sm">
              <p><span className="text-gray-500">Reason:</span> <span className="text-gray-200">{activeHandoff.reason}</span></p>
              <p><span className="text-gray-500">URL:</span> <span className="text-gray-200 font-mono text-xs">{activeHandoff.url}</span></p>
              <p><span className="text-gray-500">Message:</span> <span className="text-gray-200">{activeHandoff.message}</span></p>
            </div>
            <div>
              <label className="text-sm text-gray-400 block mb-1">Action taken</label>
              <input
                type="text"
                value={handoffAction}
                onChange={(e) => setHandoffAction(e.target.value)}
                placeholder="Describe what you did..."
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setHandoffModalOpen(false)}
                className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded text-sm transition-colors"
              >
                Dismiss
              </button>
              <button
                onClick={handleResolveHandoff}
                disabled={!handoffAction.trim()}
                className="bg-orange-600 hover:bg-orange-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
              >
                Resolve Handoff
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SessionBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'bg-green-900/50 text-green-400',
    idle: 'bg-yellow-900/50 text-yellow-400',
    closed: 'bg-gray-700 text-gray-400',
    expired: 'bg-red-900/50 text-red-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] ?? 'bg-gray-700 text-gray-400'}`}>
      {status}
    </span>
  )
}
