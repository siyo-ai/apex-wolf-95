import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { Camera, Plus, Mic, Send, Settings, History, Users, LineChart, AlertTriangle, Loader2 } from 'lucide-react'
import axios from 'axios'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'https://apex-wolf-95.onrender.com'

function TabBar() {
  const loc = useLocation()
  const tabs = [
    {path: '/', icon: LineChart, label: 'Chart AI'},
    {path: '/history', icon: History, label: 'History'},
    {path: '/consultants', icon: Users, label: 'AI Consultants'},
    {path: '/settings', icon: Settings, label: 'Settings'}
  ]
  return (
    <div className="fixed bottom-0 w-full bg-[#0a0a0a] border-t border-cyan-900/30 flex justify-around py-2 z-50">
      {tabs.map(t => (
        <Link key={t.path} to={t.path} className={`flex flex-col items-center text-xs ${loc.pathname===t.path?'text-cyan-400':'text-gray-500'}`}>
          <t.icon size={22} strokeWidth={1.5}/>
          {t.label}
        </Link>
      ))}
    </div>
  )
}

function ChartAI() {
  const [prompt, setPrompt] = useState('')
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')

  const handleAnalyze = async () => {
    if (!file &&!prompt) return alert('Upload chart or type question')
    setLoading(true)
    setResult('')
    const formData = new FormData()
    if(file) formData.append('chart', file)
    formData.append('prompt', prompt || 'Analyze this chart for SMC setup')
    
    try {
      const res = await axios.post(`${BACKEND_URL}/analyze`, formData)
      setResult(res.data.status === 'sent'? `✅ Signal sent to Telegram: ${res.data.direction}` : `❌ ${res.data.reason}\n\nVision: ${res.data.vision}`)
      setPrompt('')
      setFile(null)
    } catch (e) {
      setResult(`Error: ${e.response?.data?.msg || e.message}`)
    }
    setLoading(false)
  }

  return (
    <div className="bg-black min-h-screen text-white pb-20">
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-cyan-400">Chart AI</h1>
          <div className="bg-cyan-500/20 px-3 py-1 rounded-full text-cyan-400 text-sm">⭐ PRO</div>
        </div>
        
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 mb-4 flex gap-2">
          <AlertTriangle size={20} className="text-yellow-500 mt-0.5"/>
          <span className="text-sm text-yellow-500">Educational only. Not financial advice. Demo first.</span>
        </div>

        {result && <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3 mb-4 text-sm whitespace-pre-wrap">{result}</div>}

        <div className="border border-cyan-500/50 rounded-xl p-4 mb-4">
          <div className="flex items-center gap-3 mb-2">
            <LineChart className="text-cyan-400" />
            <span className="text-cyan-300">AI Assistant for Optimal Entry</span>
          </div>
          <button 
            onClick={() => document.getElementById('chart-upload').click()}
            className="w-full bg-cyan-500/20 border border-cyan-500 rounded-lg py-8 flex items-center justify-center"
          >
            {file? <span className="text-cyan-400">{file.name}</span> : <Camera size={40} className="text-cyan-400"/>}
          </button>
          <input id="chart-upload" type="file" accept="image/*" className="hidden" onChange={e=>setFile(e.target.files[0])}/>
        </div>

        <div className="fixed bottom-20 left-0 right-0 px-4">
          <div className="bg-[#1a1a1a] rounded-2xl p-2 flex items-center gap-2 border border-cyan-900/50">
            <Plus size={24} className="text-cyan-400"/>
            <Camera size={24} className="text-cyan-400" onClick={()=>document.getElementById('chart-upload').click()}/>
            <input 
              className="flex-1 bg-transparent outline-none text-white placeholder-gray-500" 
              placeholder="Ask me anything or type XAUUSD..."
              value={prompt}
              onChange={e=>setPrompt(e.target.value)}
              onKeyDown={e=>e.key==='Enter'&&handleAnalyze()}
            />
            {loading? <Loader2 size={24} className="text-cyan-400 animate-spin"/> : <Send size={24} className="text-cyan-400" onClick={handleAnalyze}/>}
          </div>
        </div>
      </div>
    </div>
  )
}

function History() {
  const [signals, setSignals] = useState([])
  useEffect(() => {
    axios.get(`${BACKEND_URL}/history`).then(r=>setSignals(r.data.signals))
  }, [])
  
  return <div className="bg-black min-h-screen text-white p-4 pb-20">
    <h1 className="text-2xl font-bold text-cyan-400 mb-4">Analysis History</h1>
    {signals.length === 0 && <p className="text-gray-500">No signals yet. Upload a chart or wait for Gmail alert.</p>}
    {signals.map((s,i) => (
      <div key={i} className="bg-[#1a1a1a] rounded-lg p-4 mb-3 border border-cyan-900/30">
        <p className="text-cyan-300 font-bold">{s.pair} {s.direction}</p>
        <p className="text-gray-400 text-sm">{new Date(s.time).toLocaleString()}</p>
        <p className="text-gray-500 text-xs mt-2">Entry: {s.entry}</p>
      </div>
    ))}
  </div>
}

function AIConsultants() {
  const [selected, setSelected] = useState('AI Forex Strategist')
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState('')
  const [loading, setLoading] = useState(false)
  
  const bots = [
    'AI Commodity Trading Specialist',
    'AI Day Trading Specialist', 
    'AI ETF & Index Consultant',
    'AI Forex Strategist',
    'AI Fundamental Analyst'
  ]

  const askConsultant = async () => {
    if(!query) return
    setLoading(true)
    try {
      const res = await axios.post(`${BACKEND_URL}/consultants`, {specialist: selected, query, pair: 'XAUUSD'})
      setResponse(res.data.response)
    } catch(e) {
      setResponse(`Error: ${e.message}`)
    }
    setLoading(false)
  }

  return <div className="bg-black min-h-screen text-white p-4 pb-20">
    <h1 className="text-2xl font-bold text-cyan-400 mb-4">AI Consultants</h1>
    <select 
      className="w-full bg-[#1a1a1a] border border-cyan-500/50 rounded-lg p-3 mb-4 text-cyan-300"
      value={selected} 
      onChange={e=>setSelected(e.target.value)}
    >
      {bots.map(b => <option key={b}>{b}</option>)}
    </select>
    {response && <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3 mb-4 text-sm">{response}</div>}
    <div className="flex gap-2">
      <input 
        className="flex-1 bg-[#1a1a1a] border border-cyan-900/50 rounded-lg p-3 outline-none text-white" 
        placeholder="Ask your specialist..."
        value={query}
        onChange={e=>setQuery(e.target.value)}
      />
      {loading? <Loader2 className="animate-spin text-cyan-400"/> : <Send size={24} className="text-cyan-400 mt-2" onClick={askConsultant}/>}
    </div>
  </div>
}

function Settings() {
  return <div className="bg-black min-h-screen text-white p-4 pb-20">
    <h1 className="text-2xl font-bold text-cyan-400 mb-4">Account</h1>
    <div className="bg-cyan-500/20 rounded-xl p-3 mb-4">
      <p className="text-cyan-300">Apex Wolf 9.5/10</p>
      <p className="text-gray-400 text-sm">Backend: {BACKEND_URL}</p>
    </div>
    <div className="space-y-4 text-cyan-300">
      <p>Demo Account: #436233200</p>
      <p>Risk: 0.25% per trade</p>
      <p className="text-yellow-500">Disclaimer: Educational only</p>
    </div>
  </div>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChartAI/>} />
        <Route path="/history" element={<History/>} />
        <Route path="/consultants" element={<AIConsultants/>} />
        <Route path="/settings" element={<Settings/>} />
      </Routes>
      <TabBar/>
    </BrowserRouter>
  )
}
