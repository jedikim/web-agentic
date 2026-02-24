import { useEffect, useState } from 'react'
import {
  sessions,
  type HandoffItem,
  type Session,
  type SessionDetail,
} from '../api'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-900/50 text-green-400',
  idle: 'bg-yellow-900/50 text-yellow-400',
  closed: 'bg-gray-700 text-gray-400',
  expired: 'bg-red-900/50 text-red-400',
}

const STATUS_OPTIONS = ['all', 'active', 'idle', 'closed', 'expired'] as const

export default function Sessions() {
  const [list, setList] = useState<Session[]>([])
  const [selected, setSelected] = useState<SessionDetail | null>(null)
  const [handoffs, setHandoffs] = useState<HandoffItem[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const refresh = async () => {
    try {
      const data = await sessions.list(statusFilter === 'all' ? undefined : statusFilter)
      setList(data)
    } catch (e) {
      console.error('Failed to load sessions:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [statusFilter])

  const handleSelect = async (id: string) => {
    try {
      const [detail, ho] = await Promise.all([
        sessions.get(id),
        sessions.handoffs(id),
      ])
      setSelected(detail)
      setHandoffs(ho)
    } catch (e) {
      console.error('Failed to load session detail:', e)
    }
  }

  const handleClose = async (id: string) => {
    try {
      await sessions.close(id)
      await refresh()
      if (selected?.id === id) {
        const updated = await sessions.get(id)
        setSelected(updated)
      }
    } catch (e) {
      console.error('Failed to close session:', e)
    }
  }

  if (loading) return <p className="text-gray-500">Loading...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Sessions</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Session list */}
        <div className="col-span-1 space-y-2">
          {list.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSelect(s.id)}
              className={`w-full text-left bg-gray-800/50 hover:bg-gray-800 rounded p-3 transition-colors ${
                selected?.id === s.id ? 'ring-1 ring-indigo-500' : ''
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-mono truncate">{s.id}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ml-2 ${STATUS_COLORS[s.status] ?? 'bg-gray-700 text-gray-400'}`}>
                  {s.status}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                <span>{s.turn_count} turns</span>
                <span>${s.total_cost_usd.toFixed(4)}</span>
                <span className={s.headless ? '' : 'text-blue-400'}>{s.headless ? 'headless' : 'headful'}</span>
              </div>
              {s.current_url && (
                <p className="text-xs text-gray-600 mt-0.5 truncate">{s.current_url}</p>
              )}
              <p className="text-xs text-gray-600 mt-0.5">{new Date(s.last_activity).toLocaleString()}</p>
            </button>
          ))}
          {list.length === 0 && (
            <p className="text-gray-500 text-sm">No sessions found</p>
          )}
        </div>

        {/* Detail panel */}
        <div className="col-span-2">
          {selected ? (
            <div className="bg-gray-800/50 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Session {selected.id}</h2>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[selected.status] ?? 'bg-gray-700 text-gray-400'}`}>
                  {selected.status}
                </span>
              </div>

              {/* Session metadata */}
              <div className="grid grid-cols-3 gap-3">
                <MetaCard label="Total Cost" value={`$${selected.total_cost_usd.toFixed(4)}`} />
                <MetaCard label="Turns" value={String(selected.turn_count)} />
                <MetaCard label="Tokens" value={String(selected.total_tokens)} />
              </div>

              <div className="flex gap-4 text-xs text-gray-500">
                {selected.initial_url && (
                  <span>Initial: <span className="text-gray-400 font-mono">{selected.initial_url}</span></span>
                )}
                {selected.current_url && (
                  <span>Current: <span className="text-gray-400 font-mono">{selected.current_url}</span></span>
                )}
              </div>

              {/* Turn history */}
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-2">Turn History ({selected.turns.length})</h3>
                {selected.turns.length === 0 ? (
                  <p className="text-gray-500 text-sm">No turns yet</p>
                ) : (
                  <div className="space-y-2">
                    {selected.turns.map((t) => (
                      <div key={t.id} className="bg-gray-900 rounded p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono text-gray-500">#{t.turn_num}</span>
                            <span className="text-sm text-gray-300">{t.intent}</span>
                          </div>
                          <span className={`text-xs font-medium ${t.success ? 'text-green-400' : 'text-red-400'}`}>
                            {t.success ? 'OK' : 'FAIL'}
                          </span>
                        </div>
                        <div className="flex gap-3 mt-1 text-xs text-gray-500">
                          <span>{t.steps_ok}/{t.steps_total} steps</span>
                          <span>${t.cost_usd.toFixed(4)}</span>
                          <span>{t.tokens_used} tokens</span>
                          {t.started_at && <span>{new Date(t.started_at).toLocaleTimeString()}</span>}
                        </div>
                        {t.error_msg && (
                          <p className="text-xs text-red-400 mt-1">{t.error_msg}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Pending handoffs */}
              {handoffs.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-orange-400 mb-2">
                    Pending Handoffs ({handoffs.length})
                  </h3>
                  <div className="space-y-2">
                    {handoffs.map((h) => (
                      <div key={h.request_id} className="bg-orange-900/20 border border-orange-800/50 rounded p-3">
                        <p className="text-sm text-orange-200">{h.reason}</p>
                        <p className="text-xs text-gray-400 mt-1">{h.message}</p>
                        <p className="text-xs text-gray-500 mt-1 font-mono">{h.url}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              {selected.status === 'active' && (
                <div className="pt-2 border-t border-gray-700">
                  <button
                    onClick={() => handleClose(selected.id)}
                    className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded text-sm font-medium transition-colors"
                  >
                    Close Session
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-gray-800/50 rounded-lg p-8 text-center text-gray-500">
              Select a session to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-900 rounded p-3">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="text-lg font-bold mt-1">{value}</p>
    </div>
  )
}
