import { useEffect, useState } from 'react'
import { versions, type VersionRecord } from '../api'

export default function Versions() {
  const [records, setRecords] = useState<VersionRecord[]>([])
  const [current, setCurrent] = useState('')
  const [selected, setSelected] = useState<VersionRecord | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const [recs, cur] = await Promise.all([versions.list(), versions.current()])
      setRecords(recs)
      setCurrent(cur.version)
    } catch (e) {
      console.error('Failed to load versions:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const handleRollback = async (version: string) => {
    if (!confirm(`Rollback to version ${version}?`)) return
    await versions.rollback(version)
    await refresh()
  }

  if (loading) return <p className="text-gray-500">Loading...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Versions</h1>
        <span className="text-sm text-gray-400">
          Current: <span className="text-white font-medium">v{current}</span>
        </span>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="col-span-1 space-y-2">
          {records.map((v) => (
            <button
              key={v.id}
              onClick={() => setSelected(v)}
              className={`w-full text-left rounded p-3 transition-colors ${
                selected?.id === v.id
                  ? 'bg-gray-800 ring-1 ring-indigo-500'
                  : 'bg-gray-800/50 hover:bg-gray-800'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  v{v.version}
                  {v.version === current && (
                    <span className="ml-2 text-xs text-green-400">(current)</span>
                  )}
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                {new Date(v.created_at).toLocaleString()}
              </p>
              {v.previous_version && (
                <p className="text-xs text-gray-600">from v{v.previous_version}</p>
              )}
            </button>
          ))}
          {records.length === 0 && (
            <p className="text-gray-500 text-sm">No versions recorded yet</p>
          )}
        </div>

        {/* Detail */}
        <div className="col-span-2">
          {selected ? (
            <div className="bg-gray-800/50 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Version {selected.version}</h2>
                {selected.git_tag && (
                  <span className="text-xs text-gray-400 font-mono">{selected.git_tag}</span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-gray-500 text-xs">Previous Version</p>
                  <p>{selected.previous_version ?? 'None'}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Git Commit</p>
                  <p className="font-mono text-xs">{selected.git_commit ?? '-'}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Evolution Run</p>
                  <p className="font-mono text-xs">{selected.evolution_run_id ?? '-'}</p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs">Created</p>
                  <p>{new Date(selected.created_at).toLocaleString()}</p>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-1">Changelog</h3>
                <pre className="text-xs text-gray-300 bg-gray-900 rounded p-3 whitespace-pre-wrap">
                  {selected.changelog}
                </pre>
              </div>

              {selected.version !== current && (
                <button
                  onClick={() => handleRollback(selected.version)}
                  className="bg-yellow-600 hover:bg-yellow-700 px-4 py-2 rounded text-sm font-medium transition-colors"
                >
                  Rollback to this version
                </button>
              )}
            </div>
          ) : (
            <div className="bg-gray-800/50 rounded-lg p-8 text-center text-gray-500">
              Select a version to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
