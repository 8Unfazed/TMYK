import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { io, Socket } from 'socket.io-client';
import { ArrowRight, Check, Clipboard, Crown, Eye, LoaderCircle, LockKeyhole, RefreshCw, Sparkles, Users, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { downloadResults, getSocketUrl, getToken, request, setToken } from './api';
import FlipCard from './components/FlipCard';
import SlideCommit from './components/SlideCommit';
import { Description, GameMode, GameState, Player } from './types';

type RoomResponse = { token: string; state: GameState };
const ROUND_TIMER_OPTIONS = [
  { label: '30 seconds', value: 30 },
  { label: '1 minute', value: 60 },
  { label: '1 minute 30 seconds', value: 90 },
  { label: '2 minutes', value: 120 },
] as const;

function DescriptionFlipCard({
  description,
  title,
  metadata,
  defaultFlipped = false,
  className = '',
}: {
  description: Pick<Description, 'id' | 'sequence' | 'text'>;
  title: string;
  metadata: ReactNode;
  defaultFlipped?: boolean;
  className?: string;
}) {
  const number = String((description.sequence ?? 0) + 1).padStart(2, '0');
  const text = description.text?.trim() || 'This description is unavailable.';
  return <FlipCard
    key={description.id}
    front={<div className="description-flip-front">
      <Sparkles size={30} aria-hidden="true" />
      <span className="description-flip-eyebrow">{title}</span>
      <strong>#{number}</strong>
      <span className="description-flip-hint">CLICK OR SWIPE TO REVEAL</span>
    </div>}
    back={<div className="description-flip-back">
      <div className="description-flip-heading"><span>DESCRIPTION {number}</span><Sparkles size={15} aria-hidden="true" /></div>
      <h3>{title}</h3>
      <p className="description-flip-text">{text}</p>
      {metadata && <div className="description-flip-metadata">{metadata}</div>}
    </div>}
    axis="y"
    flipOnClick
    draggable
    dragDistance={0}
    tilt
    tiltMax={12}
    glare
    glareOpacity={0.22}
    hoverScale={1.03}
    perspective={1100}
    stiffness={170}
    damping={20}
    width={300}
    height={400}
    radius={22}
    background="#27272a"
    color="#f5f5f5"
    shadow
    shadowColor="#000000"
    shadowOpacity={0.45}
    defaultFlipped={defaultFlipped}
    ariaLabel={`${title}, description ${number}. Press Enter or Space to flip.`}
    className={`description-flip-card ${className}`.trim()}
  />;
}

function RoundTimer({ deadline, serverNow, duration }: { deadline: string | null; serverNow: string; duration: number }) {
  const [clockNow, setClockNow] = useState(Date.now());
  const clockOffsetMs = useMemo(() => Date.parse(serverNow) - Date.now(), [serverNow]);
  useEffect(() => {
    const interval = window.setInterval(() => setClockNow(Date.now()), 250);
    return () => window.clearInterval(interval);
  }, []);
  const deadlineMs = deadline ? Date.parse(deadline) : null;
  const remainingSeconds = deadlineMs === null
    ? duration
    : Math.max(0, Math.ceil((deadlineMs - (clockNow + clockOffsetMs)) / 1000));
  return <div className={`round-timer ${remainingSeconds <= 10 ? 'round-timer-low' : ''}`} role="timer" aria-label={`${Math.floor(remainingSeconds / 60)} minutes ${remainingSeconds % 60} seconds remaining`}>
    <strong>{String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:{String(remainingSeconds % 60).padStart(2, '0')}</strong>
    <span>TIME REMAINING</span>
  </div>;
}

function useGame() {
  const [state, setState] = useState<GameState | null>(null);
  const [socketStatus, setSocketStatus] = useState<'connecting' | 'connected' | 'offline'>('offline');
  const [error, setError] = useState('');
  const [closedMessage, setClosedMessage] = useState('');
  const refresh = useCallback(async () => {
    if (!getToken()) return;
    try {
      setState(await request<GameState>('/state'));
      setError('');
    } catch (err) {
      setState(null);
      setError(err instanceof Error ? err.message : 'Could not restore your game.');
    }
  }, []);
  const gameId = state?.game_id;
  const act = useCallback(async (path: string, body?: unknown) => {
    setError('');
    try {
      const next = await request<GameState>(path, {
        method: 'POST',
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      setState(next);
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Action failed.';
      setError(message);
      throw err;
    }
  }, []);
  useEffect(() => {
    if (!getToken()) return;
    void refresh();
    let socket: Socket;
    try {
      socket = io(getSocketUrl(), { auth: { token: getToken() }, reconnection: true });
    } catch (err) {
      setSocketStatus('offline');
      setError(err instanceof Error ? err.message : 'Production API is not configured.');
      return;
    }
    socket.on('connect', () => setSocketStatus('connected'));
    socket.on('disconnect', () => setSocketStatus('offline'));
    socket.on('connect_error', () => setSocketStatus('offline'));
    socket.on('room:state', (next: GameState) => setState(next));
    socket.on('game:closing', () => setState((current) => current ? { ...current, phase: 'CLOSING' } : current));
    socket.on('game:closed', () => {
      localStorage.removeItem('fourfold.session');
      setState(null);
      setError('');
      setClosedMessage('This match room has been closed.');
    });
    const interval = window.setInterval(() => {
      if (!socket.connected) void refresh();
    }, 5000);
    return () => {
      window.clearInterval(interval);
      socket.disconnect();
    };
  }, [refresh, gameId]);
  return { state, setState, socketStatus, error, setError, refresh, act, closedMessage, setClosedMessage };
}

function App() {
  const game = useGame();
  const [searchParams] = useSearchParams();
  const [name, setName] = useState('');
  const [gameMode, setGameMode] = useState<GameMode>('CLASSIC');
  const [code, setCode] = useState(searchParams.get('room')?.toUpperCase() ?? '');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const enter = async (event: FormEvent, joining: boolean) => {
    event.preventDefault();
    setBusy(true);
    game.setError('');
    try {
      const response = await request<RoomResponse>(joining ? '/rooms/join' : '/rooms', {
        method: 'POST',
        body: JSON.stringify(joining ? { name, code } : { name, game_mode: gameMode }),
      });
      setToken(response.token);
      game.setState(response.state);
    } catch (err) {
      game.setError(err instanceof Error ? err.message : 'Could not join the room.');
    } finally {
      setBusy(false);
    }
  };

  const copyInvite = async () => {
    await navigator.clipboard.writeText(`${window.location.origin}/?room=${game.state?.code}`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };
  const newRoom = () => {
    localStorage.removeItem('fourfold.session');
    game.setState(null);
    game.setError('');
    game.setClosedMessage('');
  };
  const cancelGame = async () => {
    if (!window.confirm('End this game for everyone? This cannot be undone.')) return;
    try { await game.act('/cancel'); } catch { /* parent displays the error */ }
  };

  if (!game.state) {
    return (
      <main className="landing">
        <header className="topbar"><Link to="/" className="brand" title="The More You Know"><span className="brand-mark">4</span> TMYK</Link><span className="topnote">A game of knowing your people</span></header>
        <section className="hero">
          <div className="eyebrow"><span className="eyebrow-dot" /> FOUR OR EIGHT PLAYERS · ONE VERY GOOD GUESS</div>
          <h1>How well do<br /><em>you know</em> your people?</h1>
          <p className="hero-copy">Write about your friends. Read between the lines. See who really knows who.</p>
          <div className="play-card">
            <div className="play-card-head"><div><span className="step">01 / GET TOGETHER</span><h2>Start your room</h2></div><Users size={20} /></div>
            <form onSubmit={(event) => enter(event, false)} className="entry-form">
              <label htmlFor="display-name">Your name</label>
              <input id="display-name" maxLength={24} required value={name} onChange={(e) => setName(e.target.value)} placeholder="What should we call you?" />
              <label htmlFor="game-mode">Game mode</label>
              <select id="game-mode" value={gameMode} onChange={(event) => setGameMode(event.target.value as GameMode)}>
                <option value="CLASSIC">Classic · 4 players</option>
                <option value="FULL_EXPERIENCE_8">8-Player Full Experience</option>
              </select>
              <small className="game-mode-help">{gameMode === 'FULL_EXPERIENCE_8' ? 'Play with 5–8 players. Everyone describes every other player.' : 'Exactly four players. Write about each of your three friends.'}</small>
              <button className="button button-primary" disabled={busy}>{busy ? <LoaderCircle className="spin" /> : <>Create a game <ArrowRight size={17} /></>}</button>
            </form>
            <div className="divider"><span>OR JOIN A ROOM</span></div>
            <form onSubmit={(event) => enter(event, true)} className="entry-form join-form">
              <label htmlFor="room-code">Room code</label>
              <div className="join-row"><input id="room-code" maxLength={8} required value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="E.G. A7K2QP" /><button className="button button-dark" disabled={busy}>Join <ArrowRight size={16} /></button></div>
            </form>
            {game.error && <p className="error" role="alert">{game.error}</p>}
            {game.closedMessage && <p className="success-note" role="status">{game.closedMessage}</p>}
          </div>
          <div className="how-row"><span><i>01</i> Write about everyone</span><span><i>02</i> Guess who wrote what</span><span><i>03</i> Find out who knows you</span></div>
        </section>
        <footer className="landing-footer"><span>Made for the group chat, played together.</span><span>4 or 5–8 seats · No accounts · All heart</span></footer>
      </main>
    );
  }

  const state = game.state;
  return (
    <main className="game-shell">
      <header className="game-topbar">
        <Link to="/" className="brand" title="The More You Know"><span className="brand-mark">4</span> TMYK</Link>
        <div className="room-pill"><span className="live-dot" /> ROOM <b>{state.code}</b></div>
        {state.me.id === state.host_id && !['FINISHED', 'CLOSING', 'CANCELLED'].includes(state.phase) && <button className="cancel-game" onClick={() => void cancelGame()}>End game</button>}
        <button className="icon-button" aria-label="Refresh game" onClick={() => void game.refresh()}><RefreshCw size={17} /></button>
        <span className={`connection ${game.socketStatus}`}><span />{game.socketStatus === 'connected' ? 'Live' : 'Reconnecting'}</span>
      </header>
      {game.error && <div className="toast-error" role="alert"><X size={16} />{game.error}<button onClick={() => game.setError('')} aria-label="Dismiss error"><X size={15} /></button></div>}
      {state.phase === 'LOBBY' && <Lobby state={state} act={game.act} onCopy={copyInvite} copied={copied} />}
      {state.phase === 'WRITING' && <Writing state={state} act={game.act} />}
      {state.phase === 'GUESSING' && <Guessing state={state} act={game.act} onError={game.setError} />}
      {state.phase === 'REVEAL' && <Reveal state={state} act={game.act} />}
      {state.phase === 'TIEBREAKER' && <Tiebreaker state={state} act={game.act} />}
      {(state.phase === 'FINISHED' || state.phase === 'CLOSING') && <Results state={state} act={game.act} onNew={newRoom} onClosed={() => {
        localStorage.removeItem('fourfold.session');
        game.setState(null);
        game.setClosedMessage('This match room has been closed.');
      }} onError={game.setError} />}
      {state.phase === 'CANCELLED' && <section className="phase-panel"><span className="eyebrow">ROOM CLOSED</span><h1>This game has ended.</h1><button className="button button-primary" onClick={newRoom}>Start a new game</button></section>}
      <footer className="game-footer"><span>YOU ARE PLAYER {state.me.number}</span><span>{state.player_count} PLAYERS · ONE SHARED STORY</span><span className="safe"><LockKeyhole size={13} /> Your guesses stay sealed</span></footer>
    </main>
  );
}

function PlayerCards({ players, selected, onSelect, disabled, label }: { players: Player[]; selected: string | null; onSelect: (id: string) => void; disabled?: boolean; label: string }) {
  return <div className="player-grid" role="group" aria-label={label}>
    {players.map((p) => <button type="button" key={p.id} className={`player-choice ${selected === p.id ? 'selected' : ''}`} disabled={disabled} onClick={() => onSelect(selected === p.id ? '' : p.id)} aria-pressed={selected === p.id}>
      <span className="avatar">{String(p.number).padStart(2, '0')}</span><span>{p.name}</span>{selected === p.id && <Check size={16} className="selection-check" />}
    </button>)}
  </div>;
}

export function Lobby({ state, act, onCopy, copied }: { state: GameState; act: (path: string, body?: unknown) => Promise<GameState | undefined>; onCopy: () => void; copied: boolean }) {
  const isHost = state.me.id === state.host_id;
  const capacity = state.player_capacity;
  const fullExperience = state.game_mode === 'FULL_EXPERIENCE_8';
  const readyCount = state.players.filter((p) => p.ready).length;
  const [busy, setBusy] = useState(false);
  const run = async (path: string, body?: unknown) => { setBusy(true); try { await act(path, body); } catch { /* inline game error is shown by parent */ } finally { setBusy(false); } };
  return <section className="lobby-layout">
    <div className="section-heading"><span className="eyebrow">THE GATHERING</span><h1>Make yourselves<br /><em>at home.</em></h1><p>{fullExperience ? 'Play with 5–8 players. Everyone describes every other player.' : 'Four players make the magic. Share the room and get everyone ready.'}</p></div>
    <div className="lobby-card">
      <div className="room-share"><div><span className="small-label">YOUR ROOM CODE</span><strong>{state.code}</strong></div><button className="button button-outline" onClick={onCopy}><Clipboard size={15} />{copied ? 'Copied!' : 'Copy invite'}</button></div>
      <div className="lobby-mode"><span className="small-label">SELECTED GAME MODE</span><strong>{fullExperience ? '8-Player Full Experience' : 'Classic · 4 players'}</strong></div>
      <div className="seat-heading"><span>THE {capacity} SEATS</span><span>{state.players.length} OF {capacity} JOINED</span></div>
      <div className="round-duration-setting">
        <div><strong>Round timer</strong><small>{fullExperience ? 'Every description gets the same server-controlled countdown.' : 'Each description gets its own countdown.'}</small></div>
        {fullExperience
          ? <b className="round-duration-value">ROUND TIMER: 30 SECONDS (FIXED)</b>
          : isHost
            ? <label><span className="sr-only">Round duration</span><select aria-label="Round duration" value={state.round_duration_seconds} disabled={busy} onChange={(event) => void run('/round-duration', { duration_seconds: Number(event.target.value) })}>
              {ROUND_TIMER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select></label>
            : <b className="round-duration-value">{ROUND_TIMER_OPTIONS.find((option) => option.value === state.round_duration_seconds)?.label ?? '1 minute'}</b>}
      </div>
      <div className="seats">
        {Array.from({ length: capacity }, (_, index) => index + 1).map((number) => {
          const player = state.players.find((p) => p.number === number);
          return <div key={number} className={`seat ${player ? 'occupied' : ''}`}>
            <span className="seat-number">{String(number).padStart(2, '0')}</span>
            <div className="seat-name">{player ? <><strong>{player.name}{player.id === state.me.id && <small> YOU</small>}</strong><span>{player.id === state.host_id ? <><Crown size={12} /> HOST</> : player.ready ? <><Check size={12} /> READY</> : 'GETTING SETTLED'}</span></> : <><strong>Waiting for a friend</strong><span>OPEN SEAT</span></>}</div>
            {player && <span className={`presence ${player.connected ? 'online' : ''}`} aria-label={player.connected ? 'Connected' : 'Disconnected'} />}
          </div>;
        })}
      </div>
      <div className="lobby-actions">
        <div className="ready-copy"><b>{readyCount}/{capacity} ready</b><span>{state.players.length < state.minimum_players ? `At least ${state.minimum_players} players are needed.` : isHost ? 'When everyone is ready, let the game begin.' : 'Waiting for the host to start.'}</span></div>
        {isHost && state.players.length >= state.minimum_players && state.players.length <= capacity && readyCount === state.players.length
          ? <button className="button button-primary" disabled={busy} onClick={() => void run('/start')}>Start the game <ArrowRight size={17} /></button>
          : <button className={`button ${state.players.find((p) => p.id === state.me.id)?.ready ? 'button-outline' : 'button-dark'}`} disabled={busy} onClick={() => void run('/ready', { ready: !state.players.find((p) => p.id === state.me.id)?.ready })}>{state.players.find((p) => p.id === state.me.id)?.ready ? 'I need a moment' : 'I’m ready'} <Check size={16} /></button>}
      </div>
    </div>
  </section>;
}

function Writing({ state, act }: { state: GameState; act: (path: string, body?: unknown) => Promise<GameState | undefined> }) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => Object.fromEntries(state.drafts.map((draft) => [draft.subject_id, draft.text])));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const targets = state.players.filter((p) => p.id !== state.me.id);
  const submitted = state.players.find((p) => p.id === state.me.id)?.writing_submitted ?? false;
  const descriptionsPerPlayer = state.player_count - 1;
  const save = async (targetId: string) => {
    const text = drafts[targetId] ?? '';
    if (!text.trim()) return;
    setBusy(true);
    try { await act('/descriptions/draft', { subject_id: targetId, text }); setNotice('Draft saved privately'); window.setTimeout(() => setNotice(''), 2000); }
    catch { /* parent displays the error */ }
    finally { setBusy(false); }
  };
  const submit = async () => {
    setBusy(true);
    try { await act('/descriptions/submit', { descriptions: Object.fromEntries(targets.map((p) => [p.id, drafts[p.id] ?? ''])) }); }
    catch { /* parent displays the error */ }
    finally { setBusy(false); }
  };
  return <section className="phase-layout">
    <div className="phase-intro"><span className="eyebrow">ROUND ONE · WRITE</span><h1>Describe the<br /><em>ones you know.</em></h1><p>Write one true, kind, or delightfully specific thing about each friend. They won’t know it’s yours until the reveal.</p></div>
    <div className="phase-card writing-card">
      <div className="card-topline"><span>YOUR {descriptionsPerPlayer} DESCRIPTIONS</span><span>{state.progress.writing_submitted}/{state.player_count} PLAYERS LOCKED</span></div>
      {submitted ? <div className="waiting-state"><span className="big-icon"><LockKeyhole /></span><h2>Safely tucked away.</h2><p>Your words are locked. We’ll begin once everyone has finished.</p><div className="progress-track"><i style={{ width: `${(state.progress.writing_submitted / state.player_count) * 100}%` }} /></div><small>{state.progress.writing_submitted} of {state.player_count} players finished</small></div> :
        <>
          {targets.map((target) => <div className="writing-target" key={target.id}>
            <div className="target-heading"><span className="avatar">{String(target.number).padStart(2, '0')}</span><div><strong>{target.name}</strong><span>WRITE ABOUT PLAYER {target.number}</span></div></div>
            <textarea maxLength={250} value={drafts[target.id] ?? ''} onChange={(event) => setDrafts((current) => ({ ...current, [target.id]: event.target.value }))} placeholder={`A little thing that feels like ${target.name}…`} aria-label={`Description about ${target.name}`} />
            <div className="textarea-footer"><span>Keep it anonymous, keep it kind.</span><span>{(drafts[target.id] ?? '').length}/250</span><button type="button" className="text-button" onClick={() => void save(target.id)} disabled={busy || !(drafts[target.id] ?? '').trim()}>Save draft</button></div>
          </div>)}
          <div className="submit-writing"><span>{notice || `${Object.values(drafts).filter((text) => text.trim()).length} of ${descriptionsPerPlayer} descriptions ready`}</span><button className="button button-primary" disabled={busy || targets.some((p) => !(drafts[p.id] ?? '').trim())} onClick={() => void submit()}>{busy ? 'Saving…' : 'Lock my descriptions'} <LockKeyhole size={15} /></button></div>
        </>}
    </div>
  </section>;
}

export function Guessing({ state, act, onError }: {
  state: GameState;
  act: (path: string, body?: unknown) => Promise<GameState | undefined>;
  onError: (message: string) => void;
}) {
  const active = state.active_description;
  const isAuthor = active?.is_author;
  const fullExperience = state.game_mode === 'FULL_EXPERIENCE_8';
  const authorOptions = fullExperience
    ? state.players.filter((player) => player.id !== state.me.id)
    : state.players;
  const [author, setAuthor] = useState<string | null>(null);
  const [subject, setSubject] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [commitSucceeded, setCommitSucceeded] = useState(false);
  const submissionInProgress = useRef(false);
  useEffect(() => {
    setAuthor(state.my_guess?.author_guess_id ?? null);
    setSubject(state.my_guess?.subject_guess_id ?? null);
  }, [state.active_description_id, state.my_guess]);
  useEffect(() => {
    setCommitSucceeded(false);
  }, [state.active_description_id]);
  const submit = async () => {
    if (!active) throw new Error('There is no active description to guess.');
    if (state.my_guess) throw new Error('Your guess is already locked.');
    if (!author && !subject) throw new Error('Choose an author or subject before locking your guess.');
    if (submissionInProgress.current) throw new Error('Your guess is already being submitted.');
    submissionInProgress.current = true;
    setBusy(true);
    setCommitSucceeded(false);
    try {
      const next = await act('/guesses', { description_id: active.id, author_guess_id: author || null, subject_guess_id: subject || null });
      if (!next?.my_guess) throw new Error('The server did not confirm that your guess was locked. Please try again.');
      return next;
    } finally {
      submissionInProgress.current = false;
      setBusy(false);
    }
  };
  const handleGuessLocked = () => setCommitSucceeded(true);
  const handleGuessLockError = (reason: unknown) => {
    onError(reason instanceof Error ? reason.message : 'Could not lock your guess. Please try again.');
  };
  const selectAuthor = (id: string) => setAuthor(id);
  const selectSubject = (id: string) => setSubject(id);
  if (!active) return <section className="phase-panel"><LoaderCircle className="spin" /><h2>Finding the next card…</h2></section>;
  if (isAuthor) return <section className="phase-layout"><div className="phase-intro"><span className="eyebrow">ROUND TWO · GUESS</span><h1>Your turn to<br /><em>sit this one out.</em></h1></div><div className="phase-card waiting-state"><RoundTimer deadline={state.round_deadline} serverNow={state.server_now} duration={state.round_duration_seconds} /><span className="big-icon"><Eye /></span><h2>Let the others wonder.</h2><p>Everyone else is trying to figure this one out. You’ll see the reveal when their guesses are locked.</p><div className="progress-track"><i style={{ width: `${(state.progress.guess_submitted / state.progress.guess_required) * 100}%` }} /></div><small>{state.progress.guess_submitted} of {state.progress.guess_required} guesses submitted</small></div></section>;
  const guessed = Boolean(state.my_guess);
  return <section className="phase-layout">
    <div className="phase-intro"><span className="eyebrow">ROUND TWO · GUESS</span><h1>Read the room.<br /><em>Who wrote this?</em></h1><p>Choose an author, a subject, or both. Each answer is independent. Once you lock it in, it stays sealed.</p></div>
    <div className="phase-card guess-card">
      <div className="card-topline"><span>ROUND {((active.sequence ?? 0) + 1)} OF {state.round_count}</span><span>{state.progress.guess_submitted} OF {state.progress.guess_required} GUESSES LOCKED</span></div>
      <RoundTimer deadline={state.round_deadline} serverNow={state.server_now} duration={state.round_duration_seconds} />
      <div className="guess-description">
        <DescriptionFlipCard description={active} title="Anonymous description" metadata={<span>ROUND TWO · GUESS</span>} />
      </div>
      {guessed && <div className="waiting-state compact"><span className="big-icon"><LockKeyhole /></span><h2>Your guess is in.</h2><p>It’s locked away until everyone has made their call.</p><div className="progress-track"><i style={{ width: `${(state.progress.guess_submitted / state.progress.guess_required) * 100}%` }} /></div></div>}
      {!guessed && <>
          <div className="guess-category"><div className="category-title"><span className="category-icon author-icon">✍</span><div><strong>Who wrote it?</strong><small>AUTHOR · 8 POINTS</small></div><button type="button" className="skip-button" disabled={busy} onClick={() => setAuthor(null)} aria-label="Skip author guess">Skip</button></div>
            <PlayerCards players={authorOptions} selected={author} onSelect={selectAuthor} disabled={busy} label="Choose the author" />
          </div>
          <div className="guess-category"><div className="category-title"><span className="category-icon subject-icon">◎</span><div><strong>Who is it about?</strong><small>SUBJECT · 5 POINTS</small></div><button type="button" className="skip-button" disabled={busy} onClick={() => setSubject(null)} aria-label="Skip subject guess">Skip</button></div>
            <PlayerCards players={state.players} selected={subject} onSelect={selectSubject} disabled={busy} label="Choose the subject" />
          </div>
        </>}
      <div className="guess-footer">
        <span>{guessed ? (commitSucceeded ? 'Your guess is locked.' : 'Your guess is in. Waiting for the room…') : 'Choose either or both to submit.'}</span>
        <SlideCommit
          label="Slide to lock your guess"
          doneLabel="Guess locked"
          errorLabel="Failed to lock guess"
          onConfirm={submit}
          onDone={handleGuessLocked}
          onError={handleGuessLockError}
          trackColor="#262626"
          handleColor="#f5f5f5"
          successColor="#22c55e"
          dangerColor="#e5484d"
          width={320}
          height={56}
          radius={28}
          speed={50}
          returnBounce={0.38}
          landingDip={0.026}
          holdMs={1500}
          disabled={busy || guessed || (!author && !subject)}
          className="guess-slide-commit"
        />
      </div>
    </div>
  </section>;
}

function Reveal({ state, act }: { state: GameState; act: (path: string, body?: unknown) => Promise<GameState | undefined> }) {
  const desc = state.active_description;
  const byId = useMemo(() => new Map(state.players.map((p) => [p.id, p])), [state.players]);
  const [busy, setBusy] = useState(false);
  const continueGame = async () => {
    setBusy(true);
    try { await act('/continue', { expected_version: state.version }); } catch { /* parent displays error */ } finally { setBusy(false); }
  };
  if (!desc) return null;
  return <section className="phase-layout reveal-layout">
    <div className="phase-intro"><span className="eyebrow">THE REVEAL</span><h1>And the truth<br /><em>comes out.</em></h1><p>The room’s guesses are in. Here’s how close everyone came.</p></div>
    <div className="phase-card reveal-card">
      <div className="card-topline"><span>ROUND {((desc.sequence ?? 0) + 1)} OF {state.round_count}</span><span><Sparkles size={14} /> THE ANSWER</span></div>
      <div className="reveal-description">
        <DescriptionFlipCard
          description={desc}
          title="The truth"
          defaultFlipped
          metadata={<span>Written by <b>{byId.get(desc.author_id ?? '')?.name ?? 'Unknown'}</b> about <b>{byId.get(desc.subject_id ?? '')?.name ?? 'Unknown'}</b></span>}
        />
      </div>
      <div className="answer-row"><div className="answer-item"><small>WRITTEN BY</small><strong><span className="avatar">{String(byId.get(desc.author_id ?? '')?.number ?? '?').padStart(2, '0')}</span>{byId.get(desc.author_id ?? '')?.name}</strong></div><div className="answer-item"><small>ABOUT</small><strong><span className="avatar">{String(byId.get(desc.subject_id ?? '')?.number ?? '?').padStart(2, '0')}</span>{byId.get(desc.subject_id ?? '')?.name}</strong></div></div>
      <div className="guess-results"><div className="result-heading">THE ROOM’S GUESSES <span>AUTHOR +8 · SUBJECT +5</span></div>
        {desc.guesses.map((guess) => <div className="guess-result" key={guess.guesser_id}>
          <strong>{guess.guesser_name}</strong>
          <span>Author: {byId.get(guess.author_guess_id ?? '')?.name ?? 'Skipped'} <b className={guess.author_points ? 'earned' : ''}>+{guess.author_points}</b></span>
          <span>Subject: {byId.get(guess.subject_guess_id ?? '')?.name ?? 'Skipped'} <b className={guess.subject_points ? 'earned' : ''}>+{guess.subject_points}</b></span>
        </div>)}
      </div>
      <Leaderboard state={state} />
      {state.me.id === state.host_id ? <div className="guess-footer"><span>{(desc.sequence ?? 0) + 1 === state.round_count ? 'That was the last description.' : 'Ready for the next one?'}</span><button className="button button-primary" disabled={busy} onClick={() => void continueGame()}>{busy ? 'One moment…' : (desc.sequence ?? 0) + 1 === state.round_count ? 'See the results' : 'Next description'} <ArrowRight size={16} /></button></div> : <p className="host-wait"><Crown size={14} /> Waiting for the host to continue</p>}
    </div>
  </section>;
}

export function Tiebreaker({ state, act }: { state: GameState; act: (path: string, body?: unknown) => Promise<GameState | undefined> }) {
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [author, setAuthor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isTied = state.tie_participants.includes(state.me.id);
  const participants = state.players.filter((player) => state.tie_participants.includes(player.id));
  const authorOptions = participants.filter((player) => player.id !== state.me.id);
  const active = state.active_tiebreaker;
  const playerById = new Map(state.players.map((player) => [player.id, player]));
  const submit = async (path: string, body: unknown) => {
    setBusy(true);
    try { await act(path, body); } catch { /* parent displays the error */ } finally { setBusy(false); }
  };
  const continueRound = () => active && void submit('/tiebreaker/continue', { expected_version: state.version });

  if (state.tie_stage === 'WRITING') {
    if (!isTied) return <section className="phase-layout"><div className="phase-intro"><span className="eyebrow">AUTHOR IDENTIFICATION · PREPARING</span><h1>The tied players<br /><em>are writing.</em></h1><p>All players will guess who wrote each description. Your main-game score is unchanged.</p></div><div className="phase-card waiting-state"><span className="big-icon"><Crown /></span><h2>Hang tight.</h2><p>{state.tiebreaker_progress.description_submitted} of {state.tiebreaker_progress.description_required} descriptions are locked.</p></div></section>;
    const targets = state.players.filter((player) => player.id !== state.me.id);
    const complete = targets.every((player) => Boolean(descriptions[player.id]?.trim()));
    return <section className="phase-layout">
      <div className="phase-intro"><span className="eyebrow">AUTHOR IDENTIFICATION · WRITE</span><h1>Describe everyone<br /><em>but yourself.</em></h1><p>Write one anonymous description about each other player. You will sit out the round featuring your description.</p></div>
      <div className="phase-card tie-writing-card">
        <div className="card-topline"><span>{targets.length} DESCRIPTIONS · MAX 250 CHARACTERS EACH</span><span>{state.tiebreaker_progress.description_submitted}/{state.tiebreaker_progress.description_required} LOCKED</span></div>
        {state.tiebreaker_submitted ? <div className="waiting-state compact"><span className="big-icon"><LockKeyhole /></span><h2>Your descriptions are locked.</h2><p>{state.tiebreaker_progress.waiting_player_ids.length ? `Waiting for ${state.tiebreaker_progress.waiting_player_ids.map((id) => playerById.get(id)?.name).filter(Boolean).join(', ')} to finish.` : 'All descriptions are in.'}</p></div> :
          <div className="tie-writing-list">{targets.map((subject) => <label className="tie-writing-target" key={subject.id}>
            <span>ABOUT: Player {subject.number} — {subject.name}</span>
            <textarea maxLength={250} value={descriptions[subject.id] ?? ''} onChange={(event) => setDescriptions((current) => ({ ...current, [subject.id]: event.target.value }))} placeholder="Write an anonymous description…" />
            <small>{(descriptions[subject.id] ?? '').length}/250 characters</small>
          </label>)}
          <div className="guess-footer"><span>{targets.length} descriptions required</span><button className="button button-primary" disabled={busy || !complete} onClick={() => void submit('/tiebreaker/descriptions', { descriptions })}>Lock descriptions <LockKeyhole size={15} /></button></div></div>}
      </div>
    </section>;
  }

  if (state.tie_stage === 'GUESSING' && active) {
    const subject = playerById.get(active.subject_id ?? '');
    const roundLabel = `${(active.sequence ?? 0) + 1} / ${state.tiebreaker_progress.description_required}`;
    return <section className="phase-layout">
      <div className="phase-intro"><span className="eyebrow">AUTHOR IDENTIFICATION · GUESS</span><h1>One question.<br /><em>Who wrote it?</em></h1><p>The subject is shown. Identify the tied player who wrote the description.</p></div>
      <div className="phase-card guess-card tie-round-card">
        <div className="card-topline"><span>TIEBREAKER ROUND {roundLabel}</span><span>{state.tiebreaker_progress.guess_submitted}/{state.tiebreaker_progress.guess_required} GUESSES LOCKED</span></div>
        <RoundTimer deadline={state.round_deadline} serverNow={state.server_now} duration={state.round_duration_seconds} />
        <div className="tie-subject" aria-label={`About Player ${subject?.number ?? ''}, ${subject?.name ?? 'unknown'}`}><span>ABOUT</span><strong>Player {subject?.number} — {subject?.name}</strong></div>
        <blockquote className="tie-description-text">{active.text}</blockquote>
        {active.is_author ? <div className="waiting-state compact tie-author-wait"><span className="big-icon"><Eye /></span><h2>You wrote this description.</h2><p>You sit out this round. Everyone else is locking in their author guesses.</p></div> :
          state.my_tiebreaker_guess ? <div className="waiting-state compact tie-author-wait"><span className="big-icon"><LockKeyhole /></span><h2>{state.my_tiebreaker_guess.timed_out ? 'Time expired.' : 'Guess locked.'}</h2><p>Your answer stays sealed until every eligible player has submitted or time runs out.</p></div> :
            <div className="tie-guess-entry">
              <h2>WHO WROTE THIS DESCRIPTION?</h2>
              <PlayerCards players={authorOptions} selected={author} onSelect={setAuthor} label="Choose which tied player wrote this description" />
              <div className="guess-footer"><span>Only tied players can be selected.</span><button className="button button-primary" disabled={busy || !author} onClick={() => void submit('/tiebreaker/guess', { prompt_id: active.id, author_guess_id: author })}>Lock Guess <LockKeyhole size={15} /></button></div>
            </div>}
        <div className="tie-waiting-status"><div className="progress-track"><i style={{ width: `${(state.tiebreaker_progress.guess_submitted / Math.max(1, state.tiebreaker_progress.guess_required)) * 100}%` }} /></div><small>{state.tiebreaker_progress.waiting_player_ids.length ? `Waiting for ${state.tiebreaker_progress.waiting_player_ids.map((id) => playerById.get(id)?.name).filter(Boolean).join(', ')}` : 'Everyone eligible has submitted'}</small><small>{state.tiebreaker_progress.guess_submitted} of {state.tiebreaker_progress.guess_required} eligible players submitted</small></div>
      </div>
    </section>;
  }

  if (state.tie_stage === 'REVEAL' && active) {
    const correctAuthor = playerById.get(active.author_id ?? '');
    const subject = playerById.get(active.subject_id ?? '');
    return <section className="phase-layout"><div className="phase-intro"><span className="eyebrow">TIEBREAKER · REVEAL</span><h1>One final<br /><em>reveal.</em></h1><p>Everyone except the description’s author guesses. Correct author guesses earn one point.</p></div><div className="phase-card reveal-card">
      <div className="card-topline"><span>TIEBREAKER ROUND {(active.sequence ?? 0) + 1} / {state.tiebreaker_progress.description_required}</span><span><Sparkles size={14} /> REVEAL</span></div>
      <div className="tie-subject"><span>ABOUT</span><strong>Player {subject?.number} — {subject?.name}</strong></div>
      <blockquote className="tie-description-text">{active.text}</blockquote>
      <div className="tie-correct-author"><small>CORRECT AUTHOR</small><strong>Player {correctAuthor?.number} — {correctAuthor?.name}</strong></div>
      <div className="guess-results"><div className="result-heading">ELIGIBLE PLAYERS’ GUESSES <span>+1 CORRECT · +0 INCORRECT</span></div>{active.guesses.map((guess) => {
        const guessedAuthor = playerById.get(guess.author_guess_id ?? '');
        return <div className={`guess-result tie-guess-result ${guess.points ? 'tie-correct-guess' : 'tie-incorrect-guess'}`} key={guess.guesser_id}>
          <strong>{guess.guesser_name}</strong>
          <span>{guess.timed_out ? 'No answer — time expired' : `Guessed: ${guessedAuthor?.name ?? 'No answer'}`}</span>
          <b className={guess.points ? 'earned' : ''}>{guess.points ? '+1 point' : '+0 points'}</b>
        </div>;
      })}</div>
      <div className="tie-final-leaderboard"><div className="result-heading">TIED PLAYERS · ACCUMULATED POINTS</div>{state.tiebreaker_leaderboard.map((player, index) => <div className="tie-final-row" key={player.id}><span className="leader-rank">{index + 1}</span><span>Player {player.number} — {player.name}</span><strong>{player.tiebreaker_points} {player.tiebreaker_points === 1 ? 'point' : 'points'}</strong></div>)}</div>
      <div className="guess-footer"><span>{state.me.id === state.host_id ? 'Host advances after the reveal.' : 'Waiting for the host to continue.'}</span>{state.me.id === state.host_id && <button className="button button-primary" disabled={busy} onClick={continueRound}>{busy ? 'One moment…' : (active.sequence ?? 0) + 1 === state.tiebreaker_progress.description_required ? 'See tiebreaker results' : 'Next description'} <ArrowRight size={16} /></button>}</div>
    </div></section>;
  }
  return <section className="phase-panel"><LoaderCircle className="spin" /><h2>Getting the tiebreaker ready…</h2></section>;
}

function Leaderboard({ state }: { state: GameState }) {
  return <div className="leaderboard"><div className="result-heading">MAIN-GAME LEADERBOARD</div>{state.leaderboard.map((p, i) => <div className="leader-row" key={p.id}><span className="leader-rank">{i + 1}</span><span className="leader-name">{p.name}{p.id === state.me.id && <small> YOU</small>}</span><span>{p.author_points} author · {p.subject_points} subject</span><b>{p.total}</b></div>)}</div>;
}

export function Results({ state, act, onNew, onClosed, onError }: {
  state: GameState;
  act: (path: string, body?: unknown) => Promise<GameState | undefined>;
  onNew: () => void;
  onClosed: () => void;
  onError: (message: string) => void;
}) {
  const tied = state.winners.length > 1;
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmClose, setConfirmClose] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const accept = async () => { setBusy(true); try { await act('/accept-tie'); setNotice('Joint winners accepted.'); } catch { /* parent displays error */ } finally { setBusy(false); } };
  const startTiebreaker = async () => { setBusy(true); try { await act('/tiebreaker/start'); } catch { /* parent displays error */ } finally { setBusy(false); } };
  const playerMap = useMemo(() => new Map(state.players.map((p) => [p.id, p])), [state.players]);
  const winnerNames = state.winners.map((id) => playerMap.get(id)?.name ?? 'Unknown').join(' and ');
  const isHost = state.me.id === state.host_id;
  const download = async (format: 'json' | 'csv') => {
    setBusy(true);
    setDownloadError('');
    try {
      await downloadResults(format, state.code);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not download the results.';
      setDownloadError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };
  const closeRoom = async () => {
    setBusy(true);
    onError('');
    try {
      await request<{ closed: boolean }>('/close', { method: 'POST' });
      onClosed();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not close the match room. You can safely retry.');
    } finally {
      setBusy(false);
      setConfirmClose(false);
    }
  };
  return <section className="results-layout">
    <div className="results-hero"><span className="eyebrow">THE GAME IS YOURS</span><span className="trophy"><Crown size={28} /></span><h1>{state.tie_completed ? (tied ? 'A shared tiebreaker win.' : 'Tiebreaker champion.') : tied ? 'A shared win.' : 'Well, look at you.'}</h1><p>{state.tie_completed ? `${winnerNames} ${tied ? 'share' : 'wins'} the tiebreaker.` : tied ? 'Some bonds are too close to call. These friends share the top spot.' : `${playerMap.get(state.winners[0])?.name ?? 'A player'} knows this room by heart.`}</p></div>
    <div className="phase-card results-card"><Leaderboard state={state} />    <div className="final-breakdown">{state.leaderboard.map((p) => <div key={p.id}><span>Player {p.number} · {p.name}</span><span>{p.author_points} author + {p.subject_points} subject = <b>{p.total}</b></span></div>)}</div>
      {state.tie_completed && <div className="tie-final-leaderboard"><div className="result-heading">TIEBREAKER LEADERBOARD <span>AUTHOR IDENTIFICATION POINTS</span></div>{state.tiebreaker_leaderboard.map((p, index) => <div className="tie-final-row" key={p.id}><span className="leader-rank">{index + 1}</span><span>Player {p.number} — {p.name}{state.winners.includes(p.id) && <small> WINNER</small>}</span><strong>{p.tiebreaker_points} {p.tiebreaker_points === 1 ? 'point' : 'points'}</strong></div>)}</div>}
      <div className="result-heading recap-heading">THE {state.round_count} LITTLE TRUTHS</div>
      <div className="recap-list">{state.descriptions.map((d: Description, i) => <div className="recap-item" key={d.id}>
        <DescriptionFlipCard
          description={d}
          title={`Description ${String(i + 1).padStart(2, '0')}`}
          metadata={<span>Written by <b>{playerMap.get(d.author_id ?? '')?.name ?? 'Unknown'}</b> about <b>{playerMap.get(d.subject_id ?? '')?.name ?? 'Unknown'}</b></span>}
          defaultFlipped
        />
        <details className="recap-guesses"><summary>See {d.guesses.length} guesses and points</summary>{d.guesses.map((guess) => <div className="recap-guess" key={guess.guesser_id}><b>{guess.guesser_name}</b><span>Author: {playerMap.get(guess.author_guess_id ?? '')?.name ?? 'Skipped'} (+{guess.author_points})</span><span>Subject: {playerMap.get(guess.subject_guess_id ?? '')?.name ?? 'Skipped'} (+{guess.subject_points})</span></div>)}</details>
      </div>)}</div>
      {state.tie_completed && <><div className="result-heading recap-heading">TIEBREAKER CLUES</div><div className="recap-list">{state.tiebreaker_prompts.map((prompt, i) => <div className="recap-item" key={prompt.id}>
        <DescriptionFlipCard
          description={prompt}
          title={`Tiebreaker clue ${String(i + 1).padStart(2, '0')}`}
          metadata={<span>About <b>{playerMap.get(prompt.subject_id ?? '')?.name ?? 'Unknown'}</b> · Written by <b>{playerMap.get(prompt.author_id ?? '')?.name ?? 'Unknown'}</b></span>}
          defaultFlipped
        />
        <details className="recap-guesses"><summary>See {prompt.guesses.length} tiebreaker guesses</summary>{prompt.guesses.map((guess) => <div className="recap-guess" key={guess.guesser_id}><b>{guess.guesser_name}</b><span>{guess.timed_out ? 'No answer — time expired' : `Guessed: ${playerMap.get(guess.author_guess_id ?? '')?.name ?? 'No answer'}`} (+{guess.points})</span></div>)}</details>
      </div>)}</div></>}
      {state.phase === 'FINISHED' && tied && isHost && state.tie_available && <div className="tie-action"><div><strong>Break the tie or share the win?</strong><span>Every tied player describes every other player. The whole room guesses each author for separate tiebreaker points.</span></div><div className="tie-buttons"><button className="button button-outline" disabled={busy} onClick={() => void accept()}>Accept joint winners</button><button className="button button-primary" disabled={busy} onClick={() => void startTiebreaker()}>Play tiebreaker <ArrowRight size={15} /></button></div></div>}
      {tied && state.tie_accepted && <p className="success-note"><Check size={16} />Joint winners accepted by the host.</p>}
      {notice && <p className="success-note"><Check size={16} />{notice}</p>}
      {state.phase === 'FINISHED' && <div className="result-actions">
        <button type="button" className="button button-primary" disabled={busy} onClick={() => void download('json')}>Download Results <ArrowRight size={16} /></button>
        <button type="button" className="button button-outline" disabled={busy} onClick={() => void download('csv')}>Download CSV</button>
        {isHost && <button type="button" className="button button-outline close-room" disabled={busy} onClick={() => setConfirmClose(true)}>Close Match Room</button>}
      </div>}
      {state.phase === 'CLOSING' && <p className="success-note" role="status">This match room is closing. New game actions and downloads are disabled.</p>}
      {state.phase === 'CLOSING' && isHost && <button type="button" className="button button-outline" disabled={busy} onClick={() => void closeRoom()}>Retry closing match room</button>}
      {confirmClose && <div className="dialog-backdrop"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="close-room-title">
        <h2 id="close-room-title">Close Match Room?</h2>
        <p>Closing this match permanently deletes its game data, including descriptions, guesses, and scores. Download the results first if you want to keep a copy. This action cannot be undone.</p>
        {downloadError && <p className="error" role="alert">{downloadError}</p>}
        <div className="dialog-actions">
          <button type="button" className="button button-primary" disabled={busy} onClick={() => void download('json')}>Download Results</button>
          <button type="button" className="button button-outline" disabled={busy} onClick={() => setConfirmClose(false)}>Cancel</button>
          <button type="button" className="button button-dark" disabled={busy} onClick={() => void closeRoom()}>{busy ? 'Closing…' : 'Close Match Room'}</button>
        </div>
      </section></div>}
      {state.phase !== 'CLOSING' && <button type="button" className="button button-dark new-game" onClick={onNew}><RefreshCw size={16} /> Create a new room</button>}
    </div>
  </section>;
}

export default App;
