import { useEffect, useRef, useState } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { subscribeSSE } from './api'
import Automation from './pages/Automation'
import Dashboard from './pages/Dashboard'
import Evolutions from './pages/Evolutions'
import ScenariosPage from './pages/Scenarios'
import Sessions from './pages/Sessions'
import Versions from './pages/Versions'

const NAV = [
  { path: '/', label: 'Dashboard' },
  { path: '/automation', label: 'Automation' },
  { path: '/sessions', label: 'Sessions' },
  { path: '/evolutions', label: 'Evolutions' },
  { path: '/scenarios', label: 'Scenarios' },
  { path: '/versions', label: 'Versions' },
] as const

export default function App() {
  const location = useLocation()
  const [events, setEvents] = useState<{ type: string; data: unknown; ts: number }[]>([])
  const [apiVersion, setApiVersion] = useState('')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    esRef.current = subscribeSSE((type, data) => {
      setEvents((prev) => [...prev.slice(-99), { type, data, ts: Date.now() }])
    })
    fetch('/api/health').then(r => r.json()).then(d => setApiVersion(d.version || '')).catch(() => {})
    return () => esRef.current?.close()
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Navbar */}
      <nav className="border-b border-gray-800 bg-gray-900/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 flex items-center h-14 gap-6">
          <span className="font-bold text-lg tracking-tight text-indigo-400">
            Evolution Engine
          </span>
          {apiVersion && (
            <span className="text-xs text-gray-500 font-mono">v{apiVersion}</span>
          )}
          <div className="flex gap-1">
            {NAV.map((n) => (
              <Link
                key={n.path}
                to={n.path}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  location.pathname === n.path
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                {n.label}
              </Link>
            ))}
          </div>
          {events.length > 0 && (
            <span className="ml-auto text-xs text-gray-500">
              {events.length} event(s)
            </span>
          )}
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard events={events} />} />
          <Route path="/automation" element={<Automation />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/evolutions" element={<Evolutions />} />
          <Route path="/scenarios" element={<ScenariosPage />} />
          <Route path="/versions" element={<Versions />} />
        </Routes>
      </main>
    </div>
  )
}
