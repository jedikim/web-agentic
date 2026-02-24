import { useEffect, useState } from 'react'
import {
  evolution,
  type EvolutionChange,
  type EvolutionDetail,
  type EvolutionRun,
} from '../api'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-600',
  analyzing: 'bg-blue-600',
  generating: 'bg-purple-600',
  testing: 'bg-yellow-600',
  awaiting_approval: 'bg-orange-500',
  approved: 'bg-green-600',
  merged: 'bg-green-700',
  rejected: 'bg-red-600',
  failed: 'bg-red-700',
}

export default function Evolutions() {
  const [runs, setRuns] = useState<EvolutionRun[]>([])
  const [selected, setSelected] = useState<EvolutionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)

  const refresh = async () => {
    try {
      const data = await evolution.list()
      setRuns(data)
    } catch (e) {
      console.error('Failed to load evolutions:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await evolution.trigger('manual')
      await refresh()
    } finally {
      setTriggering(false)
    }
  }

  const handleSelect = async (id: string) => {
    const detail = await evolution.get(id)
    setSelected(detail)
  }

  const handleApprove = async (id: string) => {
    await evolution.approve(id)
    setSelected(null)
    await refresh()
  }

  const handleReject = async (id: string) => {
    await evolution.reject(id)
    setSelected(null)
    await refresh()
  }

  if (loading) return <p className="text-gray-500">Loading...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Evolutions</h1>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          {triggering ? 'Triggering...' : 'Trigger Evolution'}
        </button>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Run list */}
        <div className="col-span-1 space-y-2">
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => handleSelect(r.id)}
              className={`w-full text-left bg-gray-800/50 hover:bg-gray-800 rounded p-3 transition-colors ${
                selected?.id === r.id ? 'ring-1 ring-indigo-500' : ''
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-mono">{r.id}</span>
                <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[r.status] ?? 'bg-gray-500'}`}>
                  {r.status}
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-1">{r.trigger_reason}</p>
              <p className="text-xs text-gray-600 mt-0.5">{new Date(r.created_at).toLocaleString()}</p>
            </button>
          ))}
          {runs.length === 0 && (
            <p className="text-gray-500 text-sm">No evolution runs yet</p>
          )}
        </div>

        {/* Detail panel */}
        <div className="col-span-2">
          {selected ? (
            <div className="bg-gray-800/50 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Run {selected.id}</h2>
                <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[selected.status] ?? 'bg-gray-500'}`}>
                  {selected.status}
                </span>
              </div>

              {selected.analysis_summary && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-1">Analysis</h3>
                  <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                    {selected.analysis_summary}
                  </pre>
                </div>
              )}

              {selected.error_message && (
                <div className="bg-red-900/30 border border-red-800 rounded p-3">
                  <p className="text-sm text-red-300">{selected.error_message}</p>
                </div>
              )}

              {selected.branch_name && (
                <p className="text-xs text-gray-500">
                  Branch: <span className="text-gray-300 font-mono">{selected.branch_name}</span>
                </p>
              )}

              {/* Changes */}
              {selected.changes.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-2">Changes ({selected.changes.length})</h3>
                  <div className="space-y-2">
                    {selected.changes.map((c: EvolutionChange) => (
                      <div key={c.id} className="bg-gray-900 rounded p-3">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            c.change_type === 'create' ? 'bg-green-800 text-green-200' :
                            c.change_type === 'delete' ? 'bg-red-800 text-red-200' :
                            'bg-blue-800 text-blue-200'
                          }`}>
                            {c.change_type}
                          </span>
                          <span className="text-sm font-mono">{c.file_path}</span>
                        </div>
                        <p className="text-xs text-gray-400 mt-1">{c.description}</p>
                        {c.diff_content && (
                          <pre className="text-xs mt-2 bg-gray-950 rounded p-2 overflow-x-auto">
                            {c.diff_content}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              {selected.status === 'awaiting_approval' && (
                <div className="flex gap-3 pt-2 border-t border-gray-700">
                  <button
                    onClick={() => handleApprove(selected.id)}
                    className="bg-green-600 hover:bg-green-700 px-4 py-2 rounded text-sm font-medium transition-colors"
                  >
                    Approve & Merge
                  </button>
                  <button
                    onClick={() => handleReject(selected.id)}
                    className="bg-red-600 hover:bg-red-700 px-4 py-2 rounded text-sm font-medium transition-colors"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-gray-800/50 rounded-lg p-8 text-center text-gray-500">
              Select an evolution run to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
