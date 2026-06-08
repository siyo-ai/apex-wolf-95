import { useState, useEffect } from 'react'
import axios from 'axios'
import { Loader2, TrendingUp, History as HistoryIcon, Settings as SettingsIcon } from 'lucide-react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:10000'

function App() {
  const [page, setPage] = useState('home')
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState('')
  const [loading, setLoading] = useState(false)

  const handleAnalyze = async () => {
    if (!prompt) return
    setLoading(true)
    setResponse('')
    try {
      const res = await axios.post(`${BACKEND_URL}/analyze`, { prompt })
      setResponse(res.data.analysis)
    } catch (err) {
      setResponse('Error: Backend offline or CORS issue. Check VITE_BACKEND_URL env var.')
    }
    setLoading(false)
  }

  return (
    <div className="bg-black min-h-screen text-white">
      <div className="max-w-4xl mx-auto p-4">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-cyan-400">Chart AI Pro ✝️🩸</h1>
          <div className="flex gap-4">
            <button onClick={() => setPage('home')} className="text-cyan-400 hover:text-cyan-300">
              <TrendingUp size={24} />
            </button>
            <button onClick={() => setPage('history')} className="text-cyan-400 hover:text-cyan-300">
              <HistoryIcon size={24} />
            </button>
            <button onClick={() => setPage('settings')} className="text-cyan-400 hover:text-cyan-300">
              <SettingsIcon size={24} />
            </button>
          </div>
        </div>

        {page === 'home' && (
          <div className="space-y-6">
            <div className="bg-[#1a1a1a] rounded-lg p-6 border border-cyan-500/20">
              <h2 className="text-xl font-bold text-cyan-400 mb-4">AI Market Analysis</h2>
              <textarea
                className="w-full bg-black border border-cyan-500/30 rounded p-3 text-white focus:outline-none focus:border-cyan-400"
                rows="4"
                placeholder="Ask about EURUSD, BTC, XAUUSD... e.g. 'Analyze EURUSD H1'"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleAnalyze()}
              />
              <button
                onClick={handleAnalyze}
                disabled={loading}
                className="mt-4 w-full bg-cyan-500 hover:bg-cyan-600 disabled:bg-gray-600 text-black font-bold py-3 rounded flex items-center justify-center gap-2"
              >
                {loading ? <Loader2 className="animate-spin" size={20} /> : 'Analyze'}
              </button>
            </div>

            {response && (
              <div className="bg-[#1a1a1a] rounded-lg p-6 border border-cyan-500/20">
                <h3 className="text-lg font-bold text-cyan-400 mb-3">AI Response</h3>
                <pre className="text-gray-300 whitespace-pre-wrap font-mono text-sm">{response}</pre>
              </div>
            )}
          </div>
        )}

        {page === 'history' && <History />}
        {page === 'settings' && <Settings />}
      </div>
    </div>
  )
}

function History() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get(`${BACKEND_URL}/history`)
      .then(res => setSignals(res.data))
      .catch(() => setSignals([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="bg-black min-h-screen text-white">
      <h1 className="text-2xl font-bold text-cyan-400 mb-6">Signal History</h1>
      {loading ? (
        <Loader2 className="animate-spin text-cyan-400" size={32} />
      ) : signals.length === 0 ? (
        <p className="text-gray-400">No signals yet. Run an analysis first.</p>
      ) : (
        <div className="space-y-4">
          {signals.map((s, i) => (
            <div key={i} className="bg-[#1a1a1a] rounded-lg p-4 border border-cyan-500/20">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-cyan-400 font-bold">{s.symbol} {s.direction}</p>
                  <p className="text-gray-300 text-sm">{s.timestamp}</p>
                </div>
                <span className={`px-3 py-1 rounded text-sm ${s.status === 'win' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                  {s.status}
                </span>
              </div>
              <p className="text-gray-400 text-sm mt-2">Entry: {s.entry} | TP: {s.tp} | SL: {s.sl}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Settings() {
  return (
    <div className="bg-black min-h-screen text-white">
      <h1 className="text-2xl font-bold text-cyan-400 mb-6">Settings</h1>
      <div className="bg-cyan-500/20 rounded-lg p-4 border border-cyan-500/30 mb-6">
        <p className="text-cyan-300">Apex Wolf v0.1</p>
        <p className="text-gray-400 text-sm">Educational demo only</p>
      </div>
      <div className="space-y-4 text-cyan-300">
        <p>Demo Account: #436233200</p>
        <p>Risk: 0.25% per trade</p>
        <p className="text-yellow-500">Disclaimer: This is educational code. Not financial advice.</p>
      </div>
    </div>
  )
}

export default App
