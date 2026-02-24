import { useEffect, useState } from 'react'
import { scenarios, type ScenarioResult, type ScenarioTrend } from '../api'

export default function ScenariosPage() {
  const [results, setResults] = useState<ScenarioResult[]>([])
  const [trends, setTrends] = useState<ScenarioTrend[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  const refresh = async () => {
    try {
      const [res, tr] = await Promise.all([scenarios.results(), scenarios.trends()])
      setResults(res)
      setTrends(tr)
    } catch (e) {
      console.error('Failed to load scenarios:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const handleRun = async () => {
    setRunning(true)
    try {
      await scenarios.run(true, 0.5)
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <p className="text-gray-500">Loading...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Scenarios</h1>
        <button
          onClick={handleRun}
          disabled={running}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          {running ? 'Starting...' : 'Run Scenarios'}
        </button>
      </div>

      {/* Trends */}
      {trends.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Success Trends</h2>
          <div className="grid grid-cols-3 gap-4">
            {trends.map((t) => (
              <div key={t.scenario_name} className="bg-gray-800/50 rounded-lg p-4">
                <p className="text-sm font-medium">{t.scenario_name}</p>
                <div className="mt-3 flex items-end gap-4">
                  <div>
                    <p className="text-2xl font-bold text-white">{t.success_rate.toFixed(0)}%</p>
                    <p className="text-xs text-gray-500">success rate</p>
                  </div>
                  <div>
                    <p className="text-lg font-medium">{t.total_runs}</p>
                    <p className="text-xs text-gray-500">runs</p>
                  </div>
                  <div>
                    <p className="text-lg font-medium">${t.avg_cost.toFixed(3)}</p>
                    <p className="text-xs text-gray-500">avg cost</p>
                  </div>
                  <div>
                    <p className="text-lg font-medium">{t.avg_time.toFixed(1)}s</p>
                    <p className="text-xs text-gray-500">avg time</p>
                  </div>
                </div>
                <div className="mt-2 h-2 bg-gray-700 rounded overflow-hidden">
                  <div
                    className={`h-full rounded ${t.success_rate >= 80 ? 'bg-green-500' : t.success_rate >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
                    style={{ width: `${t.success_rate}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Results table */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Results History</h2>
        {results.length === 0 ? (
          <p className="text-gray-500 text-sm">No results yet. Run scenarios to see results.</p>
        ) : (
          <div className="bg-gray-800/50 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase">
                  <th className="text-left p-3">Scenario</th>
                  <th className="text-left p-3">Status</th>
                  <th className="text-right p-3">Steps</th>
                  <th className="text-right p-3">Cost</th>
                  <th className="text-right p-3">Time</th>
                  <th className="text-right p-3">Version</th>
                  <th className="text-right p-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="p-3 font-medium">{r.scenario_name}</td>
                    <td className="p-3">
                      <span className={`text-xs font-medium ${r.overall_success ? 'text-green-400' : 'text-red-400'}`}>
                        {r.overall_success ? 'PASS' : 'FAIL'}
                      </span>
                    </td>
                    <td className="p-3 text-right text-gray-400">
                      {r.total_steps_ok}/{r.total_steps_all}
                    </td>
                    <td className="p-3 text-right text-gray-400">${r.total_cost_usd.toFixed(3)}</td>
                    <td className="p-3 text-right text-gray-400">{r.wall_time_s.toFixed(1)}s</td>
                    <td className="p-3 text-right text-gray-400">{r.version ?? '-'}</td>
                    <td className="p-3 text-right text-gray-500 text-xs">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
