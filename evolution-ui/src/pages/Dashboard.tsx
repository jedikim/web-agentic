import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  evolution,
  scenarios,
  sessions,
  versions,
  type EvolutionRun,
  type ScenarioResult,
  type ScenarioTrend,
  type Session,
} from '../api'

interface Props {
  events: { type: string; data: unknown; ts: number }[]
}

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

function Badge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[status] ?? 'bg-gray-500'}`}>
      {status}
    </span>
  )
}

export default function Dashboard({ events }: Props) {
  const [currentVersion, setCurrentVersion] = useState('...')
  const [activeRuns, setActiveRuns] = useState<EvolutionRun[]>([])
  const [recentResults, setRecentResults] = useState<ScenarioResult[]>([])
  const [trends, setTrends] = useState<ScenarioTrend[]>([])
  const [activeSessions, setActiveSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const [ver, runs, results, trendData, sessionData] = await Promise.all([
        versions.current(),
        evolution.list(5),
        scenarios.results(undefined, 10),
        scenarios.trends(),
        sessions.list('active'),
      ])
      setCurrentVersion(ver.version)
      setActiveRuns(runs)
      setRecentResults(results)
      setTrends(trendData)
      setActiveSessions(sessionData)
    } catch (e) {
      console.error('Dashboard load failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])
  useEffect(() => { if (events.length > 0) refresh() }, [events.length])

  if (loading) return <p className="text-gray-500">Loading...</p>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4">
        <Card label="Current Version" value={`v${currentVersion}`} />
        <Card label="Active Evolutions" value={String(activeRuns.filter(r => !['merged','failed','rejected'].includes(r.status)).length)} />
        <Card label="Recent Scenarios" value={`${recentResults.filter(r => r.overall_success).length}/${recentResults.length} pass`} />
        <Card label="Avg Cost" value={trends.length ? `$${(trends.reduce((s, t) => s + t.avg_cost, 0) / trends.length).toFixed(3)}` : '-'} />
      </div>

      {/* Session stats row */}
      <div className="grid grid-cols-3 gap-4">
        <Card label="Active Sessions" value={String(activeSessions.length)} />
        <Card label="Total Session Cost" value={`$${activeSessions.reduce((s, ses) => s + ses.total_cost_usd, 0).toFixed(4)}`} />
        <CardWithBadge
          label="Pending Handoffs"
          value="-"
          badge={activeSessions.length > 0}
          link="/sessions"
        />
      </div>

      {/* Active evolutions */}
      <Section title="Active Evolutions" link="/evolutions">
        {activeRuns.length === 0 ? (
          <p className="text-gray-500 text-sm">No evolution runs</p>
        ) : (
          <div className="space-y-2">
            {activeRuns.map((r) => (
              <div key={r.id} className="flex items-center justify-between bg-gray-800/50 rounded px-3 py-2">
                <div>
                  <span className="text-sm font-mono text-gray-300">{r.id}</span>
                  <span className="text-xs text-gray-500 ml-2">{r.trigger_reason}</span>
                </div>
                <Badge status={r.status} />
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Recent scenario results */}
      <Section title="Recent Scenarios" link="/scenarios">
        {recentResults.length === 0 ? (
          <p className="text-gray-500 text-sm">No results yet</p>
        ) : (
          <div className="space-y-2">
            {recentResults.slice(0, 5).map((r) => (
              <div key={r.id} className="flex items-center justify-between bg-gray-800/50 rounded px-3 py-2">
                <span className="text-sm">{r.scenario_name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">
                    {r.total_steps_ok}/{r.total_steps_all} steps | ${r.total_cost_usd.toFixed(3)}
                  </span>
                  <span className={`text-xs font-medium ${r.overall_success ? 'text-green-400' : 'text-red-400'}`}>
                    {r.overall_success ? 'PASS' : 'FAIL'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Trends */}
      <Section title="Scenario Trends">
        {trends.length === 0 ? (
          <p className="text-gray-500 text-sm">No trend data</p>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {trends.map((t) => (
              <div key={t.scenario_name} className="bg-gray-800/50 rounded p-3">
                <p className="text-sm font-medium">{t.scenario_name}</p>
                <div className="flex gap-4 mt-1 text-xs text-gray-400">
                  <span>{t.success_rate.toFixed(0)}% success</span>
                  <span>{t.total_runs} runs</span>
                  <span>${t.avg_cost.toFixed(3)} avg</span>
                </div>
                <div className="mt-2 h-1.5 bg-gray-700 rounded overflow-hidden">
                  <div
                    className="h-full bg-green-500 rounded"
                    style={{ width: `${t.success_rate}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* SSE event log */}
      {events.length > 0 && (
        <Section title="Live Events">
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {[...events].reverse().map((e, i) => (
              <div key={i} className="text-xs text-gray-400 font-mono">
                <span className="text-gray-600">{new Date(e.ts).toLocaleTimeString()}</span>{' '}
                <span className="text-indigo-400">{e.type}</span>{' '}
                {JSON.stringify(e.data)}
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="text-xl font-bold mt-1">{value}</p>
    </div>
  )
}

function CardWithBadge({ label, value, badge, link }: { label: string; value: string; badge: boolean; link?: string }) {
  const inner = (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
        {badge && (
          <span className="px-1.5 py-0.5 rounded text-xs bg-red-600 text-white">!</span>
        )}
      </div>
      <p className="text-xl font-bold mt-1">{value}</p>
    </div>
  )
  if (link) {
    return <Link to={link} className="block hover:ring-1 hover:ring-indigo-500 rounded-lg transition-all">{inner}</Link>
  }
  return inner
}

function Section({ title, link, children }: { title: string; link?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold">{title}</h2>
        {link && (
          <Link to={link} className="text-xs text-indigo-400 hover:text-indigo-300">
            View all →
          </Link>
        )}
      </div>
      {children}
    </div>
  )
}
