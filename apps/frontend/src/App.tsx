import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, ArrowRight, BarChart3, Bell, BookOpen, CalendarDays, Check,
  ChevronLeft, ChevronRight, CircleGauge, Clock3, Cloud, GraduationCap,
  Bot, History, KeyRound, LayoutDashboard, ListTodo, LockKeyhole, Menu, Moon, Play, Plus, RefreshCw,
  Monitor, Settings, ShieldCheck, Sparkles, Sun, Target, Wifi, X,
} from 'lucide-react'
import { addDays, differenceInMinutes, format, isSameDay, startOfWeek } from 'date-fns'
import './App.css'
import './App.extra.css'

type AssignmentState = 'AWAITING_CALIBRATION' | 'SCHEDULED' | 'IN_PROGRESS' | 'COMPLETED'
type Risk = 'LOW' | 'MEDIUM' | 'HIGH'
type Course = { id: number; name: string; code: string; color: string }
type Assignment = {
  id: number; title: string; description: string; due_at: string; state: AssignmentState
  base_minutes: number; estimated_minutes: number; scheduled_minutes: number
  proficiency: string | null; risk: Risk; assignment_type: string; course: Course
}
type CalendarItem = {
  id: string; title: string; start_at: string; end_at: string; kind: 'HARD' | 'PROTECTED' | 'FLOATING'
  color: string; locked: boolean; assignment_id?: number
}
type DashboardData = {
  assignments: Assignment[]; events: CalendarItem[]; calibration_count: number
  high_risk_count: number; scheduled_minutes: number
}
type CanvasStatus = {
  status: string; session_status: string; last_scan_at: string | null; next_scan_at: string | null
  courses_observed: number; last_result: string | null
}
type ActivityEvent = {
  id: number; type: string; entity_type: string | null; entity_id: string | null
  payload: Record<string, unknown>; created_at: string
}
type ProviderId = 'openai' | 'anthropic'
type ProviderModel = { id: string; label: string }
type ProviderConfiguration = { provider: string; model: string; base_url: string | null }
type NavItem = 'Today' | 'Calendar' | 'Assignments' | 'Mastery' | 'Activity' | 'Settings'

// In the packaged desktop app the main process reserves a free port at launch
// and hands it to the renderer through the preload bridge. The literal is the
// browser-only development fallback.
const API_ORIGIN = window.academicOS?.apiBaseUrl ?? 'http://127.0.0.1:8000'
const API = `${API_ORIGIN}/api/v1`

const localDate = (offset: number, hour: number, minute = 0) => {
  const date = addDays(new Date(), offset)
  date.setHours(hour, minute, 0, 0)
  return date.toISOString()
}

const courses: Course[] = [
  { id: 1, name: 'Engineering Mechanics: Statics', code: 'ME 201', color: '#3f7d5c' },
  { id: 2, name: 'Differential Equations', code: 'MATH 241', color: '#c2562f' },
  { id: 3, name: 'Intro to Engineering', code: 'ENGR 101', color: '#40628f' },
]

const demoAssignments: Assignment[] = [
  { id: 1, title: 'Truss Analysis Set', description: 'Method of joints and sections', due_at: localDate(2, 23, 59), state: 'SCHEDULED', base_minutes: 150, estimated_minutes: 180, scheduled_minutes: 180, proficiency: 'MEDIUM', risk: 'MEDIUM', assignment_type: 'Homework', course: courses[0] },
  { id: 4, title: 'Friction Quiz', description: 'Static and kinetic friction', due_at: localDate(1, 11), state: 'AWAITING_CALIBRATION', base_minutes: 60, estimated_minutes: 60, scheduled_minutes: 0, proficiency: null, risk: 'HIGH', assignment_type: 'Quiz', course: courses[0] },
  { id: 2, title: 'Laplace Transform Problems', description: 'Solve IVPs with Laplace transforms', due_at: localDate(4, 17), state: 'AWAITING_CALIBRATION', base_minutes: 120, estimated_minutes: 120, scheduled_minutes: 0, proficiency: null, risk: 'LOW', assignment_type: 'Problem set', course: courses[1] },
  { id: 3, title: 'Design Memo — Prototype Review', description: 'Two-page design review memo', due_at: localDate(6, 12), state: 'SCHEDULED', base_minutes: 90, estimated_minutes: 90, scheduled_minutes: 90, proficiency: 'HIGH', risk: 'LOW', assignment_type: 'Writing', course: courses[2] },
]

const demoEvents: CalendarItem[] = [
  { id: 'event-1', title: 'Differential Equations', start_at: localDate(0, 9), end_at: localDate(0, 9, 50), kind: 'HARD', color: '#40628f', locked: true },
  { id: 'event-2', title: 'Engineering Mechanics', start_at: localDate(0, 11), end_at: localDate(0, 12, 15), kind: 'HARD', color: '#3f7d5c', locked: true },
  { id: 'event-3', title: 'Lunch', start_at: localDate(0, 12, 30), end_at: localDate(0, 13, 15), kind: 'PROTECTED', color: '#9a6b17', locked: true },
  { id: 'block-1', title: 'Truss Analysis Set', start_at: localDate(0, 15), end_at: localDate(0, 16, 30), kind: 'FLOATING', color: '#c2562f', locked: false, assignment_id: 1 },
  { id: 'event-4', title: 'Gym', start_at: localDate(0, 18), end_at: localDate(0, 19), kind: 'PROTECTED', color: '#9a6b17', locked: true },
  { id: 'event-5', title: 'Differential Equations', start_at: localDate(1, 9), end_at: localDate(1, 9, 50), kind: 'HARD', color: '#40628f', locked: true },
  { id: 'block-2', title: 'Truss Analysis Set', start_at: localDate(1, 14), end_at: localDate(1, 15, 30), kind: 'FLOATING', color: '#c2562f', locked: false, assignment_id: 1 },
  { id: 'event-6', title: 'Engineering Lab', start_at: localDate(2, 13), end_at: localDate(2, 15), kind: 'HARD', color: '#3f7d5c', locked: true },
  { id: 'block-3', title: 'Design Memo', start_at: localDate(3, 16), end_at: localDate(3, 17, 30), kind: 'FLOATING', color: '#c2562f', locked: false, assignment_id: 3 },
]

const demoData: DashboardData = { assignments: demoAssignments, events: demoEvents, calibration_count: 2, high_risk_count: 1, scheduled_minutes: 270 }

const minutesLabel = (minutes: number) => minutes >= 60 ? `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ''}` : `${minutes}m`
const stateLabel = (state: string) => state.toLowerCase().replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase())

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const THEME_KEY = 'cadence-theme'
const prefersDark = () => typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches

function readStoredTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch { /* storage can be unavailable; fall through to the default */ }
  return 'system'
}

/** Tracks the user's choice, resolves 'system' against the OS, and follows OS changes live. */
function useTheme(): [ThemeChoice, ResolvedTheme, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(readStoredTheme)
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(() => (prefersDark() ? 'dark' : 'light'))

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setSystemTheme(event.matches ? 'dark' : 'light')
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const resolved: ResolvedTheme = choice === 'system' ? systemTheme : choice

  useEffect(() => {
    document.documentElement.dataset.theme = resolved
    try { localStorage.setItem(THEME_KEY, choice) } catch { /* non-fatal */ }
  }, [choice, resolved])

  return [choice, resolved, setChoice]
}

const NAV_SECTIONS: [string, [NavItem, typeof LayoutDashboard][]][] = [
  ['Plan', [['Today', LayoutDashboard], ['Calendar', CalendarDays], ['Assignments', ListTodo]]],
  ['Insights', [['Mastery', BarChart3], ['Activity', History]]],
  ['Workspace', [['Settings', Settings]]],
]

function Sidebar({ active, onChange, mobileOpen, onClose, canvasStatus }: { active: NavItem; onChange: (item: NavItem) => void; mobileOpen: boolean; onClose: () => void; canvasStatus: CanvasStatus }) {
  return <>
    {mobileOpen && <button className="scrim" aria-label="Close navigation" onClick={onClose} />}
    <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
      <div className="brand"><div className="brand-mark"><GraduationCap size={18} /></div><div><strong>Cadence</strong><span>Academic planner</span></div></div>
      <nav>{NAV_SECTIONS.map(([section, items]) => <Fragment key={section}>
        <div className="nav-label">{section}</div>
        {items.map(([label, Icon]) => <button key={label} className={active === label ? 'active' : ''} onClick={() => { onChange(label); onClose() }}><Icon size={17} /><span>{label}</span>{label === 'Assignments' && <em>4</em>}</button>)}
      </Fragment>)}</nav>
      <div className="sidebar-bottom">
        <div className="sync-card"><div className="sync-icon"><Cloud size={16} /></div><div><strong>Local workspace</strong><span>Canvas {canvasStatus.status.toLowerCase()}</span></div><span className={`status-dot ${canvasStatus.status === 'CONNECTED' ? 'online' : ''}`} /></div>
        <div className="profile"><div className="avatar">AS</div><div><strong>Alex Student</strong><span>Fall semester</span></div><button aria-label="Open settings"><Settings size={16} /></button></div>
      </div>
    </aside>
  </>
}

function Header({ active, onMenu, resolvedTheme, setTheme, onSync, syncing }: { active: NavItem; onMenu: () => void; resolvedTheme: ResolvedTheme; setTheme: (v: ThemeChoice) => void; onSync: () => void; syncing: boolean }) {
  return <header><div className="header-title"><button className="mobile-menu" onClick={onMenu} aria-label="Open navigation"><Menu size={20} /></button><div><p>{format(new Date(), 'EEEE, MMMM d')}</p><h1>{active === 'Today' ? 'Today' : active}</h1></div></div><div className="header-actions"><button className="icon-button" onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}>{resolvedTheme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button><button className="icon-button notification" aria-label="Notifications"><Bell size={18} /><span /></button><button className="sync-button" onClick={onSync} disabled={syncing}><RefreshCw size={16} className={syncing ? 'spin' : ''} />{syncing ? 'Syncing…' : 'Sync Canvas'}</button></div></header>
}

function ThemeSetting({ theme, setTheme }: { theme: ThemeChoice; setTheme: (v: ThemeChoice) => void }) {
  const options: [ThemeChoice, string, typeof Sun][] = [['light', 'Light', Sun], ['dark', 'Dark', Moon], ['system', 'System', Monitor]]
  return <div className="setting"><div><strong>Appearance</strong><span>System follows your macOS light and dark setting.</span></div><div className="theme-toggle" role="group" aria-label="Appearance">{options.map(([value, label, Icon]) => <button key={value} className={theme === value ? 'active' : ''} onClick={() => setTheme(value)} aria-pressed={theme === value}><Icon size={14} />{label}</button>)}</div></div>
}

function StatStrip({ data }: { data: DashboardData }) {
  const [renderedAt] = useState(() => Date.now())
  const dueSoon = data.assignments.filter(a => new Date(a.due_at).getTime() - renderedAt < 3 * 86400000).length
  return <section className="stat-strip">
    <div><span className="stat-icon sage"><Clock3 size={18} /></span><p><strong>{minutesLabel(data.scheduled_minutes)}</strong><small>Scheduled this week</small></p><em>on track</em></div>
    <div><span className="stat-icon blue"><ListTodo size={18} /></span><p><strong>{dueSoon}</strong><small>Due in 72 hours</small></p><em className="neutral">stay focused</em></div>
    <div><span className="stat-icon amber"><Target size={18} /></span><p><strong>{data.calibration_count}</strong><small>Need calibration</small></p><em className="attention">action needed</em></div>
    <div><span className="stat-icon coral"><AlertTriangle size={18} /></span><p><strong>{data.high_risk_count}</strong><small>Deadline at risk</small></p><em className="risk">review now</em></div>
  </section>
}

function TodayTimeline({ events }: { events: CalendarItem[] }) {
  const today = events.filter(e => isSameDay(new Date(e.start_at), new Date())).sort((a, b) => +new Date(a.start_at) - +new Date(b.start_at))
  return <section className="panel today-panel"><div className="panel-heading"><div><span className="eyebrow">Today’s rhythm</span><h2>Focus timeline</h2></div><button className="text-button">Open day <ArrowRight size={15} /></button></div>
    <div className="timeline">{today.map((event, index) => <div className="timeline-row" key={event.id}><time>{format(new Date(event.start_at), 'h:mm')}<small>{format(new Date(event.start_at), 'a')}</small></time><div className="timeline-line"><span style={{ background: event.color }} />{index < today.length - 1 && <i />}</div><article className={`timeline-event ${event.kind.toLowerCase()}`} style={{ '--event-color': event.color } as React.CSSProperties}><div><strong>{event.title}</strong><span>{event.kind === 'FLOATING' ? 'AI-planned focus block' : event.kind === 'PROTECTED' ? 'Protected time' : 'Calendar event'}</span></div><div className="event-meta"><span>{differenceInMinutes(new Date(event.end_at), new Date(event.start_at))} min</span>{event.locked ? <LockKeyhole size={13} /> : <Sparkles size={13} />}</div></article></div>)}</div>
  </section>
}

function WeekCalendar({ events, weekOffset, setWeekOffset }: { events: CalendarItem[]; weekOffset: number; setWeekOffset: (n: number) => void }) {
  const weekStart = startOfWeek(addDays(new Date(), weekOffset * 7), { weekStartsOn: 1 })
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  const hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
  return <section className="panel calendar-panel"><div className="panel-heading calendar-heading"><div><span className="eyebrow">Week plan</span><h2>{format(weekStart, 'MMMM yyyy')}</h2></div><div className="week-controls"><button onClick={() => setWeekOffset(weekOffset - 1)} aria-label="Previous week"><ChevronLeft size={17} /></button><button onClick={() => setWeekOffset(0)}>Today</button><button onClick={() => setWeekOffset(weekOffset + 1)} aria-label="Next week"><ChevronRight size={17} /></button></div></div>
    <div className="calendar-scroll"><div className="week-grid"><div className="time-header" />{days.map(day => <div className={`day-header ${isSameDay(day, new Date()) ? 'current' : ''}`} key={day.toISOString()}><span>{format(day, 'EEE').toUpperCase()}</span><strong>{format(day, 'd')}</strong></div>)}
      {hours.map(hour => <div className="week-row" key={hour} style={{ gridColumn: '1 / -1' }}><time>{format(new Date(2020, 1, 1, hour), 'ha')}</time>{days.map(day => <div className="day-cell" key={day.toISOString()}>{events.filter(event => isSameDay(new Date(event.start_at), day) && new Date(event.start_at).getHours() === hour).map(event => <button title={event.title} key={event.id} className={`calendar-event ${event.kind.toLowerCase()}`} style={{ '--event-color': event.color } as React.CSSProperties}><strong>{event.title}</strong><span>{format(new Date(event.start_at), 'h:mm')}–{format(new Date(event.end_at), 'h:mm')}</span></button>)}</div>)}</div>)}
    </div></div>
    <div className="calendar-legend"><span><i className="hard-dot" />Fixed</span><span><i className="floating-dot" />Adaptive study</span><span><i className="protected-dot" />Protected</span></div>
  </section>
}

function AssignmentQueue({ assignments, onCalibrate }: { assignments: Assignment[]; onCalibrate: (a: Assignment) => void }) {
  return <section className="panel assignment-panel"><div className="panel-heading"><div><span className="eyebrow">Next up</span><h2>Assignment queue</h2></div><button className="text-button">View all <ArrowRight size={15} /></button></div><div className="assignment-list">{assignments.map(a => <article className="assignment-row" key={a.id}><span className="course-line" style={{ background: a.course.color }} /><div className="assignment-main"><span className="course-code">{a.course.code}</span><strong>{a.title}</strong><small>Due {format(new Date(a.due_at), 'EEE, MMM d · h:mm a')}</small></div><div className="assignment-duration"><strong>{minutesLabel(a.estimated_minutes)}</strong><small>{a.scheduled_minutes ? `${minutesLabel(a.scheduled_minutes)} planned` : 'Not scheduled'}</small></div><div className="assignment-status">{a.state === 'AWAITING_CALIBRATION' ? <button className="calibrate" onClick={() => onCalibrate(a)}><Play size={12} fill="currentColor" /> Calibrate</button> : <span className={`risk-pill ${a.risk.toLowerCase()}`}>{a.risk === 'LOW' ? <Check size={12} /> : <CircleGauge size={12} />}{a.risk.toLowerCase()} risk</span>}</div></article>)}</div></section>
}

function FocusCard({ assignment }: { assignment: Assignment | undefined }) {
  if (!assignment) return null
  const percent = Math.min(100, Math.round((assignment.scheduled_minutes / assignment.estimated_minutes) * 100))
  return <aside className="focus-card"><span className="eyebrow">Focus signal</span><div className="focus-title"><div><small>{assignment.course.code}</small><h3>{assignment.title}</h3></div><span>{assignment.risk}</span></div><div className="ring-wrap"><div className="progress-ring" style={{ '--progress': `${percent * 3.6}deg` } as React.CSSProperties}><div><strong>{percent}%</strong><span>planned</span></div></div><p><strong>{minutesLabel(assignment.scheduled_minutes)}</strong> of {minutesLabel(assignment.estimated_minutes)} placed before the safety buffer.</p></div><div className="focus-note"><Sparkles size={16} /><p><strong>Why this plan?</strong><span>Your medium mastery in truss methods adds 30 minutes and splits work across two afternoons.</span></p></div><button className="primary-button">Review schedule <ArrowRight size={15} /></button></aside>
}

function CanvasWorkerCard({ status, onConnect }: { status: CanvasStatus; onConnect: () => void }) {
  const connected = status.status === 'CONNECTED'
  return <aside className="panel worker-card"><div className="worker-heading"><div className={`worker-icon ${connected ? 'online' : ''}`}><Wifi size={18} /></div><div><span className="eyebrow">Canvas worker</span><h3>{connected ? 'Session ready' : 'Browser session paused'}</h3></div></div><p>{status.last_result || 'Connect once, sign in yourself, and Cadence will keep the isolated browser profile local.'}</p><dl><div><dt>Last scan</dt><dd>{status.last_scan_at ? format(new Date(status.last_scan_at), 'MMM d · h:mm a') : 'Not yet'}</dd></div><div><dt>Courses seen</dt><dd>{status.courses_observed}</dd></div><div><dt>Next check</dt><dd>{status.next_scan_at ? format(new Date(status.next_scan_at), 'MMM d · h:mm a') : 'After connection'}</dd></div></dl><button className={connected ? 'secondary-button' : 'primary-button'} onClick={onConnect}>{connected ? 'Open Canvas session' : 'Connect Canvas'}</button></aside>
}

function AssignmentsView({ assignments, onCalibrate }: { assignments: Assignment[]; onCalibrate: (a: Assignment) => void }) {
  return <div className="full-view"><div className="view-intro"><div><span className="eyebrow">Workload</span><h2>Every deadline, one clear plan.</h2><p>Calibration gates final scheduling so estimates reflect what you actually know.</p></div><button className="primary-button"><Plus size={16} /> Add assignment</button></div><div className="assignment-table"><div className="table-head"><span>Assignment</span><span>Due</span><span>Estimate</span><span>State</span><span>Risk</span></div>{assignments.map(a => <div className="table-row" key={a.id}><div className="table-assignment"><i style={{ background: a.course.color }} /><div><strong>{a.title}</strong><small>{a.course.code} · {a.assignment_type}</small></div></div><span>{format(new Date(a.due_at), 'MMM d, h:mm a')}</span><span>{minutesLabel(a.estimated_minutes)}</span><span className="state-text">{stateLabel(a.state)}</span><span>{a.state === 'AWAITING_CALIBRATION' ? <button className="calibrate" onClick={() => onCalibrate(a)}>Calibrate</button> : <span className={`risk-pill ${a.risk.toLowerCase()}`}>{a.risk}</span>}</span></div>)}</div></div>
}

function MasteryView() {
  const rows = [{ course: 'Engineering Mechanics: Statics', topic: 'Equilibrium', score: 91, evidence: 9 }, { course: 'Engineering Mechanics: Statics', topic: 'Method of Joints', score: 84, evidence: 7 }, { course: 'Engineering Mechanics: Statics', topic: 'Method of Sections', score: 57, evidence: 4 }, { course: 'Differential Equations', topic: 'Laplace Transforms', score: 68, evidence: 3 }]
  return <div className="full-view"><div className="view-intro"><div><span className="eyebrow">Mastery map</span><h2>Knowledge, measured with restraint.</h2><p>Scores move gradually as evidence accumulates—not on a model’s hunch.</p></div></div><div className="mastery-layout"><section className="panel mastery-card"><h3>{rows[0].course}</h3>{rows.slice(0, 3).map(r => <div className="mastery-row" key={r.topic}><div><strong>{r.topic}</strong><small>{r.evidence} observations</small></div><div className="mastery-bar"><i style={{ width: `${r.score}%` }} /></div><b>{r.score}%</b></div>)}</section><section className="panel mastery-card"><h3>{rows[3].course}</h3>{rows.slice(3).map(r => <div className="mastery-row" key={r.topic}><div><strong>{r.topic}</strong><small>{r.evidence} observations</small></div><div className="mastery-bar"><i style={{ width: `${r.score}%` }} /></div><b>{r.score}%</b></div>)}<div className="mastery-callout"><Target size={20} /><p><strong>Next calibration opportunity</strong><span>Laplace Transform Problems can raise confidence from 48%.</span></p></div></section></div></div>
}

function ActivityView({ events }: { events: ActivityEvent[] }) {
  return <div className="full-view"><div className="view-intro"><div><span className="eyebrow">Audit trail</span><h2>Every meaningful change, visible.</h2><p>Worker observations become normalized events before they can affect your plan.</p></div></div><section className="panel activity-card">{events.length === 0 && <div className="activity-empty">No changes recorded yet.</div>}{events.map(event => <article className="activity-row" key={event.id}><div className="activity-mark"><History size={15} /></div><div><strong>{stateLabel(event.type.replaceAll('.', '_'))}</strong><span>{event.entity_type ? `${stateLabel(event.entity_type)} ${event.entity_id || ''}` : 'System event'}</span></div><time>{format(new Date(event.created_at), 'MMM d · h:mm a')}</time></article>)}</section></div>
}

function ModelProviderSettings({ onMessage }: { onMessage: (message: string) => void }) {
  const [provider, setProvider] = useState<ProviderId>('openai')
  const [apiKey, setApiKey] = useState('')
  const [models, setModels] = useState<ProviderModel[]>([])
  const [model, setModel] = useState('')
  const [savedModels, setSavedModels] = useState<Partial<Record<ProviderId, string>>>({})
  const [hasKey, setHasKey] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let active = true
    fetch(`${API}/providers`).then(response => response.json()).then((configurations: ProviderConfiguration[]) => {
      if (!active) return
      const saved: Partial<Record<ProviderId, string>> = {}
      for (const configuration of configurations) {
        if (configuration.provider === 'openai' || configuration.provider === 'anthropic') saved[configuration.provider] = configuration.model
      }
      setSavedModels(saved)
    }).catch(() => undefined)
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    if (!window.academicOS) return
    window.academicOS.providers.hasKey(provider).then(value => { if (active) setHasKey(value) }).catch(() => { if (active) setHasKey(false) })
    return () => { active = false }
  }, [provider])

  const changeProvider = (nextProvider: ProviderId) => {
    setProvider(nextProvider); setModels([]); setModel(''); setApiKey(''); setHasKey(false)
  }

  const loadModels = async () => {
    if (!window.academicOS) { onMessage('Provider setup is available in the desktop app.'); return }
    setLoading(true)
    try {
      if (apiKey.trim()) {
        await window.academicOS.providers.saveKey(provider, apiKey)
        setApiKey(''); setHasKey(true)
      }
      const available = await window.academicOS.providers.listModels(provider)
      setModels(available)
      const savedModel = savedModels[provider]
      if (available.length) setModel(available.some(item => item.id === savedModel) ? savedModel! : available[0].id)
      onMessage(`${available.length} models available for this ${provider === 'openai' ? 'OpenAI' : 'Anthropic'} key.`)
    } catch (error) { onMessage(error instanceof Error ? error.message : 'Could not load provider models.') }
    finally { setLoading(false) }
  }

  const chooseModel = async () => {
    if (!model) return
    setLoading(true)
    try {
      const response = await fetch(`${API}/providers/${provider}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model }) })
      if (!response.ok) throw new Error('The model selection could not be saved.')
      setSavedModels(current => ({ ...current, [provider]: model }))
      onMessage(`${models.find(item => item.id === model)?.label || model} is now the Academic Brain.`)
    } catch (error) { onMessage(error instanceof Error ? error.message : 'Could not save the model.') }
    finally { setLoading(false) }
  }

  return <section className="panel provider-card"><div className="provider-title"><div className="provider-icon"><Bot size={18} /></div><div><span className="eyebrow">Academic Brain</span><h3>Choose your model</h3><p>The picker shows models available to the API key you provide.</p></div></div><div className="provider-tabs"><button className={provider === 'openai' ? 'active' : ''} onClick={() => changeProvider('openai')}>OpenAI</button><button className={provider === 'anthropic' ? 'active' : ''} onClick={() => changeProvider('anthropic')}>Anthropic</button></div><label className="provider-field"><span><KeyRound size={13} /> API key</span><div><input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={hasKey ? 'Key stored securely — enter to replace' : `Enter ${provider === 'openai' ? 'OpenAI' : 'Anthropic'} API key`} autoComplete="off" spellCheck={false} /><button onClick={loadModels} disabled={loading || (!hasKey && !apiKey.trim())}>{loading ? 'Checking…' : hasKey && !apiKey.trim() ? 'Refresh models' : 'Save & load models'}</button></div><small>Encrypted by the operating system. It is never saved in the planner database.</small></label>{models.length > 0 && <label className="provider-field"><span>Available model</span><div><select value={model} onChange={event => setModel(event.target.value)}>{models.map(item => <option value={item.id} key={item.id}>{item.label}{item.label === item.id ? '' : ` · ${item.id}`}</option>)}</select><button className="select-model" onClick={chooseModel} disabled={loading || !model}>Use model</button></div></label>}</section>
}

function SettingsView({ canvasStatus, onConnect, onMessage, theme, setTheme }: { canvasStatus: CanvasStatus; onConnect: () => void; onMessage: (message: string) => void; theme: ThemeChoice; setTheme: (v: ThemeChoice) => void }) {
  return <div className="full-view"><div className="view-intro"><div><span className="eyebrow">Preferences</span><h2>Shape the rules. Keep control.</h2><p>Deterministic scheduling honors these boundaries every time.</p></div></div><div className="settings-layout"><section className="panel settings-card"><ThemeSetting theme={theme} setTheme={setTheme} /><div className="setting"><div><strong>Day boundary</strong><span>Study blocks may be placed between these hours.</span></div><div className="field-pair"><button>8:00 AM</button><span>to</span><button>10:00 PM</button></div></div><div className="setting"><div><strong>Maximum focus block</strong><span>Longer work is split into sustainable sessions.</span></div><button>90 minutes</button></div><div className="setting"><div><strong>Deadline safety buffer</strong><span>Finish comfortably before the real deadline.</span></div><button>12 hours</button></div><div className="setting privacy-setting"><div><strong><ShieldCheck size={15} /> Local-first privacy</strong><span>Credentials stay encrypted in the desktop vault. Models receive only the minimum task context.</span></div><b>On device</b></div><div className="integration-row"><div><span className="integration-icon">C</span><p><strong>Canvas LMS</strong><small>{canvasStatus.status === 'CONNECTED' ? 'Managed browser session connected' : 'Manual sign-in · no Canvas API token'}</small></p></div><button onClick={onConnect}>{canvasStatus.status === 'CONNECTED' ? 'Open session' : 'Connect'}</button></div></section><ModelProviderSettings onMessage={onMessage} /></div></div>
}

function CalibrationModal({ assignment, onClose, onCompleted }: { assignment: Assignment; onClose: () => void; onCompleted: (message: string) => void }) {
  const [questions, setQuestions] = useState<{ id: number; dimension: string; prompt: string }[]>([])
  const [answers, setAnswers] = useState(['', '', ''])
  const [position, setPosition] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { fetch(`${API}/assignments/${assignment.id}/calibration`).then(response => response.json()).then(result => setQuestions(result.questions || [])).catch(() => setQuestions([])) }, [assignment.id])
  const question = questions[position]
  const submit = async () => {
    if (position < 2) { setPosition(position + 1); return }
    setSubmitting(true)
    try {
      const response = await fetch(`${API}/assignments/${assignment.id}/calibration`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers }) })
      if (!response.ok) throw new Error('Calibration could not be completed')
      const result = await response.json()
      onCompleted(`Estimate updated to ${minutesLabel(result.estimated_minutes)} and ${result.blocks_created} study blocks placed.`)
    } catch (error) { onCompleted(error instanceof Error ? error.message : 'Calibration failed.') }
    finally { setSubmitting(false) }
  }
  return <div className="modal-wrap" role="dialog" aria-modal="true"><div className="modal"><div className="modal-top"><div><span className="eyebrow">3-question calibration</span><h2>{assignment.title}</h2></div><button onClick={onClose} aria-label="Close"><X size={19} /></button></div><div className="question-progress">{[0, 1, 2].map(index => <i className={index <= position ? 'done' : ''} key={index} />)}<span>Question {position + 1} of 3</span></div><div className="question-type"><BookOpen size={16} /> {question ? stateLabel(question.dimension) : 'Loading calibration'}</div><h3>{question?.prompt || 'Preparing your three-question calibration…'}</h3><textarea value={answers[position]} onChange={event => setAnswers(current => current.map((answer, index) => index === position ? event.target.value : answer))} placeholder="Write your reasoning here…" autoFocus /><div className="modal-note"><LockKeyhole size={14} /> Answers are stored locally; live Brain grading uses only this assignment context.</div><div className="modal-actions">{position > 0 ? <button className="secondary-button" onClick={() => setPosition(position - 1)}>Back</button> : <button className="secondary-button" onClick={onClose}>Save for later</button>}<button className="primary-button" onClick={submit} disabled={!question || !answers[position].trim() || submitting}>{submitting ? 'Updating plan…' : position === 2 ? 'Finish calibration' : <>Next question <ArrowRight size={15} /></>}</button></div></div></div>
}

function App() {
  const [active, setActive] = useState<NavItem>('Today')
  const [data, setData] = useState<DashboardData>(demoData)
  const [connected, setConnected] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [weekOffset, setWeekOffset] = useState(0)
  const [theme, resolvedTheme, setTheme] = useTheme()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [calibration, setCalibration] = useState<Assignment | null>(null)
  const [toast, setToast] = useState('')
  const [canvasStatus, setCanvasStatus] = useState<CanvasStatus>({ status: 'DISCONNECTED', session_status: 'NOT_CONFIGURED', last_scan_at: null, next_scan_at: null, courses_observed: 0, last_result: 'Connect Canvas to begin' })
  const [activity, setActivity] = useState<ActivityEvent[]>([])

  useEffect(() => {
    Promise.all([fetch(`${API}/dashboard`), fetch(`${API}/canvas/status`), fetch(`${API}/activity?limit=50`)]).then(async ([dashboard, status, events]) => {
      if (!dashboard.ok || !status.ok || !events.ok) throw new Error()
      setData(await dashboard.json()); setCanvasStatus(await status.json()); setActivity(await events.json()); setConnected(true)
    }).catch(() => setConnected(false))
  }, [])
  useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(''), 3000); return () => clearTimeout(id) }, [toast])
  const focusAssignment = useMemo(() => data.assignments.find(a => a.risk === 'MEDIUM' && a.state === 'SCHEDULED') || data.assignments[0], [data.assignments])

  const sync = async () => {
    setSyncing(true)
    try {
      if (connected) {
        const request = await fetch(`${API}/canvas/scan-requests`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ integrity_scan: false }) })
        if (!request.ok) throw new Error('Unable to queue Canvas scan')
        await new Promise(resolve => setTimeout(resolve, 900))
        const [dashboard, status, events] = await Promise.all([fetch(`${API}/dashboard`), fetch(`${API}/canvas/status`), fetch(`${API}/activity?limit=50`)])
        if (dashboard.ok) setData(await dashboard.json())
        if (status.ok) setCanvasStatus(await status.json())
        if (events.ok) setActivity(await events.json())
      } else await new Promise(r => setTimeout(r, 800))
      setToast(connected ? 'Canvas scan queued. Duplicate requests are safely merged.' : 'Demo refreshed. Start the API to persist changes.')
    } finally { setSyncing(false) }
  }

  const connectCanvas = async () => {
    if (!window.academicOS) { setToast('Canvas browser sessions are available in the desktop app.'); return }
    try {
      const result = await window.academicOS.canvas.connect()
      setCanvasStatus(current => ({ ...current, status: result.status === 'connected' ? 'CONNECTED' : result.status.toUpperCase(), session_status: result.status.toUpperCase(), last_result: result.status === 'auth_required' ? 'Finish signing in in the Canvas window.' : 'Managed Canvas browser is ready.' }))
      setToast(result.status === 'auth_required' ? 'Finish signing in in the Canvas window.' : 'Canvas browser session opened.')
    } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to open Canvas browser.') }
  }

  const calibrationCompleted = async (message: string) => {
    setCalibration(null); setToast(message)
    if (!connected) return
    const [dashboard, events] = await Promise.all([fetch(`${API}/dashboard`), fetch(`${API}/activity?limit=50`)])
    if (dashboard.ok) setData(await dashboard.json())
    if (events.ok) setActivity(await events.json())
  }

  return <div className="app-shell"><Sidebar active={active} onChange={setActive} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} canvasStatus={canvasStatus} /><main><Header active={active} onMenu={() => setMobileOpen(true)} resolvedTheme={resolvedTheme} setTheme={setTheme} onSync={sync} syncing={syncing} />
    {active === 'Today' && <div className="dashboard"><div className="mode-banner"><span><i className={connected ? 'connected' : ''} />{connected ? 'Local engine connected' : 'Previewing resilient demo data'}</span><small>{connected ? 'SQLite is authoritative' : 'Start the API to persist scheduling decisions'}</small></div><StatStrip data={data} /><div className="dashboard-grid"><TodayTimeline events={data.events} /><div className="dashboard-rail"><FocusCard assignment={focusAssignment} /><CanvasWorkerCard status={canvasStatus} onConnect={connectCanvas} /></div><WeekCalendar events={data.events} weekOffset={weekOffset} setWeekOffset={setWeekOffset} /><AssignmentQueue assignments={data.assignments} onCalibrate={setCalibration} /></div></div>}
    {active === 'Calendar' && <div className="full-view"><WeekCalendar events={data.events} weekOffset={weekOffset} setWeekOffset={setWeekOffset} /></div>}
    {active === 'Assignments' && <AssignmentsView assignments={data.assignments} onCalibrate={setCalibration} />}
    {active === 'Mastery' && <MasteryView />}
    {active === 'Activity' && <ActivityView events={activity} />}
    {active === 'Settings' && <SettingsView canvasStatus={canvasStatus} onConnect={connectCanvas} onMessage={setToast} theme={theme} setTheme={setTheme} />}
  </main>{calibration && <CalibrationModal assignment={calibration} onClose={() => setCalibration(null)} onCompleted={calibrationCompleted} />}{toast && <div className="toast"><Check size={16} />{toast}</div>}</div>
}

export default App
