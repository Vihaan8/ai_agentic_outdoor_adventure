import { useState, useRef, useEffect } from 'react'
import './App.css'

const API = 'http://localhost:8001'

const EXAMPLES = [
  'Moderate hikes near Boulder, CO this weekend',
  'Easy trails under 5 miles near Asheville, NC',
  'Weekend camping trip in Yosemite',
  'Sunrise hike ideas near Sedona, AZ',
]

const TOOL_META = {
  search_trails: {
    icon: '🥾',
    action: (input) => `Searching trails near ${input.location}${input.radius_km ? ` (${input.radius_km}km radius)` : ''}`,
    summarize: (r) => {
      if (r.error) return `couldn't reach trail database`
      const n = r.count || r.trails?.length || 0
      return n > 0 ? `found ${n} trail${n === 1 ? '' : 's'}` : 'no trails found'
    },
  },
  get_weather: {
    icon: '🌤',
    action: (input) => `Checking the ${input.days || 3}-day forecast for ${input.location}`,
    summarize: (r) => {
      if (r.error) return `weather unavailable`
      const n = r.forecast?.length || 0
      if (n === 0) return 'no forecast returned'
      const today = r.forecast[0]
      return `${n}-day forecast · ${today.high_f}°/${today.low_f}° · ${today.conditions}`
    },
  },
  get_daylight: {
    icon: '🌅',
    action: (input) => `Getting sunrise and sunset for ${input.location}`,
    summarize: (r) => {
      if (r.error) return `daylight unavailable`
      return `${r.sunrise} → ${r.sunset} · ${r.day_length}`
    },
  },
  get_park_info: {
    icon: '🏞',
    action: (input) => `Looking up ${input.park_query} in the national park database`,
    summarize: (r) => {
      if (r.error) return `park info unavailable`
      const parks = r.parks || []
      if (!parks.length) return 'no matching parks'
      const alertCount = parks.reduce((sum, p) => sum + (p.alerts?.length || 0), 0)
      return `${parks.length} park${parks.length === 1 ? '' : 's'}${alertCount ? ` · ${alertCount} active alert${alertCount === 1 ? '' : 's'}` : ''}`
    },
  },
}

const defaultMeta = (name) => ({
  icon: '⚙',
  action: () => name,
  summarize: () => 'done',
})

function TrailCard({ trail }) {
  return (
    <div className="card trail-card">
      <div className="card-title">{trail.name}</div>
      <div className="card-meta">
        {trail.difficulty && trail.difficulty !== 'unknown' && (
          <span className="chip">{trail.difficulty}</span>
        )}
        {trail.surface && trail.surface !== 'unknown' && (
          <span className="chip chip-soft">{trail.surface}</span>
        )}
        {trail.type && <span className="chip chip-soft">{trail.type}</span>}
      </div>
    </div>
  )
}

function WeatherCard({ day }) {
  return (
    <div className="card weather-card">
      <div className="card-title">{day.date}</div>
      <div className="temp-row">
        <span className="temp-high">{day.high_f}°</span>
        <span className="temp-low">/ {day.low_f}°</span>
      </div>
      <div className="weather-cond">{day.conditions}</div>
      <div className="weather-meta">
        💧 {day.rain_probability}% · 💨 {day.wind_mph} mph
      </div>
    </div>
  )
}

function DaylightCard({ data }) {
  return (
    <div className="card daylight-card">
      <div className="card-title">
        Daylight · {data.date}
        {data.timezone && <span className="card-sub"> · {data.timezone}</span>}
      </div>
      <div className="daylight-row">
        <div>
          <div className="daylight-label">Sunrise</div>
          <div className="daylight-time">{data.sunrise}</div>
        </div>
        <div>
          <div className="daylight-label">Sunset</div>
          <div className="daylight-time">{data.sunset}</div>
        </div>
        <div>
          <div className="daylight-label">Day length</div>
          <div className="daylight-time">{data.day_length}</div>
        </div>
      </div>
    </div>
  )
}

function ResultCards({ toolResults }) {
  const cards = []

  for (const tr of toolResults) {
    const { name, result } = tr
    if (result?.error) continue

    if (name === 'search_trails' && result.trails?.length) {
      cards.push(
        <div key={`trails-${cards.length}`} className="card-group">
          <h3>Trails near {result.location?.split(',')[0]}</h3>
          <div className="card-grid">
            {result.trails.slice(0, 6).map((t, i) => <TrailCard key={i} trail={t} />)}
          </div>
        </div>
      )
    } else if (name === 'get_weather' && result.forecast?.length) {
      cards.push(
        <div key={`weather-${cards.length}`} className="card-group">
          <h3>Forecast</h3>
          <div className="card-grid">
            {result.forecast.map((d, i) => <WeatherCard key={i} day={d} />)}
          </div>
        </div>
      )
    } else if (name === 'get_daylight' && result.sunrise) {
      cards.push(
        <div key={`daylight-${cards.length}`} className="card-group">
          <DaylightCard data={result} />
        </div>
      )
    } else if (name === 'get_park_info' && result.parks?.length) {
      cards.push(
        <div key={`park-${cards.length}`} className="card-group">
          <h3>Park info</h3>
          {result.parks.slice(0, 2).map((p, i) => (
            <div key={i} className="card park-card">
              <div className="card-title">{p.name}</div>
              <p className="park-desc">{p.description}</p>
              {p.alerts?.length > 0 && (
                <div className="alerts">
                  <strong>⚠ {p.alerts.length} active alert{p.alerts.length > 1 ? 's' : ''}</strong>
                  {p.alerts.slice(0, 2).map((a, j) => (
                    <div key={j} className="alert-item">{a.title}</div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )
    }
  }

  return cards.length > 0 ? <div className="results">{cards}</div> : null
}

function TraceStep({ step }) {
  if (step.type === 'thought') {
    return (
      <div className="trace-step trace-thought">
        <span className="trace-icon">💭</span>
        <span className="trace-text">{step.text}</span>
      </div>
    )
  }
  const meta = TOOL_META[step.name] || defaultMeta(step.name)
  return (
    <div className={`trace-step trace-tool ${step.status}`}>
      <span className="trace-step-num">{step.step}</span>
      <span className="trace-icon">{meta.icon}</span>
      <div className="trace-body">
        <div className="trace-action">{meta.action(step.input)}</div>
        {step.status === 'done' && step.summary && (
          <div className="trace-summary">→ {step.summary}</div>
        )}
      </div>
      {step.status === 'pending' ? (
        <div className="trace-dots"><span></span><span></span><span></span></div>
      ) : (
        <span className="trace-check">✓</span>
      )}
    </div>
  )
}

function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="message user-message">
        <div className="bubble user-bubble">{msg.content}</div>
      </div>
    )
  }

  const activeStep = msg.trace?.find((s) => s.status === 'pending')
  const hasTrace = msg.trace && msg.trace.length > 0
  const isWorking = msg.isStreaming

  return (
    <div className="message agent-message">
      {(hasTrace || isWorking) && (
        <div className="trace">
          <div className="trace-header">
            <span className={`agent-pulse ${isWorking ? 'active' : ''}`}>
              <span className="pulse-dot"></span>
              <span className="pulse-ring"></span>
            </span>
            <div className="trace-header-text">
              <div className="trace-title">
                {isWorking ? 'Agent working' : 'Agent trace'}
              </div>
              <div className="trace-subtitle">
                {isWorking && activeStep
                  ? (TOOL_META[activeStep.name]?.action(activeStep.input) || 'Thinking…')
                  : isWorking
                  ? 'Thinking about your request…'
                  : `${msg.trace.filter((s) => s.type !== 'thought').length} tool call${msg.trace.filter((s) => s.type !== 'thought').length === 1 ? '' : 's'}`}
              </div>
            </div>
          </div>
          {hasTrace && (
            <div className="trace-steps">
              {msg.trace.map((step, i) => <TraceStep key={i} step={step} />)}
            </div>
          )}
        </div>
      )}
      {msg.toolResults && <ResultCards toolResults={msg.toolResults} />}
      {msg.final && (
        <div className="bubble agent-bubble">
          {msg.final.split('\n').map((line, i) => <p key={i}>{line || '\u00A0'}</p>)}
        </div>
      )}
    </div>
  )
}

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [messages])

  const send = async (text) => {
    const userText = (text ?? input).trim()
    if (!userText || isStreaming) return
    setInput('')
    setIsStreaming(true)

    setMessages((m) => [
      ...m,
      { role: 'user', content: userText },
      { role: 'agent', final: '', trace: [], toolResults: [], isStreaming: true },
    ])

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const chunk of events) {
          if (!chunk.startsWith('data: ')) continue
          const event = JSON.parse(chunk.slice(6))

          setMessages((m) => {
            const updated = [...m]
            const last = { ...updated[updated.length - 1] }
            last.trace = [...(last.trace || [])]
            last.toolResults = [...(last.toolResults || [])]

            if (event.type === 'tool_call') {
              last.trace.push({
                type: 'tool',
                name: event.name,
                input: event.input,
                status: 'pending',
                step: (last.trace.filter((s) => s.type === 'tool').length + 1),
              })
            } else if (event.type === 'tool_result') {
              const pending = [...last.trace].reverse().find(
                (t) => t.type === 'tool' && t.name === event.name && t.status === 'pending'
              )
              if (pending) {
                pending.status = 'done'
                const meta = TOOL_META[event.name]
                pending.summary = meta ? meta.summarize(event.result) : 'done'
              }
              last.toolResults.push({ name: event.name, result: event.result })
            } else if (event.type === 'text') {
              // Interim text (before tool calls) → treat as a thought
              // Final text (with done) → becomes the final response
              last.pendingText = event.content
            } else if (event.type === 'done') {
              last.final = event.final_text || last.pendingText || ''
              last.pendingText = null
              last.isStreaming = false
            }

            // Promote pending text to a thought if a tool call comes after
            if (event.type === 'tool_call' && last.pendingText) {
              // Insert the thought before the just-added tool call
              const newStep = last.trace.pop()
              last.trace.push({ type: 'thought', text: last.pendingText })
              last.trace.push(newStep)
              last.pendingText = null
            }

            updated[updated.length - 1] = last
            return updated
          })
        }
      }
    } catch (err) {
      setMessages((m) => {
        const updated = [...m]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Error: ${err.message}. Is the server running on ${API}?`,
        }
        return updated
      })
    } finally {
      setIsStreaming(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <span className="logo-mark">⛰</span>
          <div>
            <h1>Trail Adventure Planner</h1>
            <p className="tagline">Tell me where, I'll plan the rest</p>
          </div>
        </div>
      </header>

      <main className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="welcome">
            <h2>Plan your next outdoor adventure</h2>
            <p>Ask about trails, weather, camping, or a weekend trip anywhere.</p>
            <div className="examples">
              {EXAMPLES.map((ex, i) => (
                <button key={i} className="example-chip" onClick={() => send(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
      </main>

      <form
        className="input-bar"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Where do you want to go?"
          disabled={isStreaming}
        />
        <button type="submit" disabled={isStreaming || !input.trim()}>
          {isStreaming ? 'Planning…' : 'Plan'}
        </button>
      </form>
    </div>
  )
}

export default App
