import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import App, { Guessing, Lobby, Results, Tiebreaker } from './App';
import { GameState } from './types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('creates an eight-player room when the full experience mode is selected', async () => {
  localStorage.clear();
  const lobbyState = {
    game_id: 'game-8',
    code: 'A8BCDE',
    phase: 'LOBBY',
    version: 1,
    game_mode: 'FULL_EXPERIENCE_8',
    player_capacity: 8,
    minimum_players: 5,
    player_count: 1,
    round_count: 0,
    round_duration_seconds: 30,
    round_started_at: null,
    round_deadline: null,
    server_now: '2026-01-01T12:00:00Z',
    host_id: 'player-1',
    me: { id: 'player-1', number: 1, name: 'Host' },
    players: [{ id: 'player-1', number: 1, name: 'Host', ready: false, connected: true }],
    active_description_id: null,
    active_description: null,
    descriptions: [],
    drafts: [],
    my_guess: null,
    progress: { writing_submitted: 0, guess_submitted: 0, guess_required: 0 },
    leaderboard: [],
    winners: [],
    tie_accepted: false,
    tie_completed: false,
    tie_available: false,
    tie_stage: null,
    tie_participants: [],
    tiebreaker_progress: { description_submitted: 0, description_required: 0, guess_submitted: 0, guess_required: 0, waiting_player_ids: [] },
    tiebreaker_submitted: false,
    active_tiebreaker: null,
    tiebreaker_prompts: [],
    my_tiebreaker_guess: null,
    tiebreaker_leaderboard: [],
  } as GameState;
  const fetchMock = vi.fn().mockResolvedValueOnce({
    ok: true,
    json: async () => ({ token: 'session-token-123456789012345678901234', state: lobbyState }),
  }).mockResolvedValue({
    ok: true,
    json: async () => lobbyState,
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<BrowserRouter><App /></BrowserRouter>);
  fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Host' } });
  fireEvent.change(screen.getByLabelText('Game mode'), { target: { value: 'FULL_EXPERIENCE_8' } });
  fireEvent.click(screen.getByRole('button', { name: /create a game/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
    name: 'Host',
    game_mode: 'FULL_EXPERIENCE_8',
  });
  expect(await screen.findByText('8-Player Full Experience')).toBeInTheDocument();
  expect(screen.getByText('ROUND TIMER: 30 SECONDS (FIXED)')).toBeInTheDocument();
  expect(screen.getAllByText('OPEN SEAT')).toHaveLength(7);
  expect(screen.queryByLabelText('Round duration')).not.toBeInTheDocument();
});

describe('landing page', () => {
  it('explains the game and provides room creation and joining', () => {
    localStorage.clear();
    render(<BrowserRouter><App /></BrowserRouter>);
    expect(screen.getByRole('heading', { name: /how well do you know your people/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create a game/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /join/i })).toBeInTheDocument();
  });

  const finishedState = {
    game_id: 'game-1',
    code: 'AB12CD',
    phase: 'FINISHED',
    version: 1,
    game_mode: 'CLASSIC',
    player_capacity: 4,
    minimum_players: 4,
    player_count: 4,
    round_count: 12,
    round_duration_seconds: 60,
    round_started_at: null,
    round_deadline: null,
    server_now: '2026-01-01T12:00:00Z',
    host_id: 'player-1',
    me: { id: 'player-1', number: 1, name: 'Host' },
    players: [{ id: 'player-1', number: 1, name: 'Host', ready: true, connected: true }],
    active_description_id: null,
    active_description: null,
    descriptions: [],
    drafts: [],
    my_guess: null,
    progress: { writing_submitted: 4, guess_submitted: 0, guess_required: 0 },
    leaderboard: [],
    winners: ['player-1'],
    tie_accepted: false,
    tie_completed: false,
    tie_available: false,
    tie_stage: null,
    tie_participants: [],
    tiebreaker_progress: { description_submitted: 0, description_required: 0, guess_submitted: 0, guess_required: 0, waiting_player_ids: [] },
    tiebreaker_submitted: false,
    active_tiebreaker: null,
    tiebreaker_prompts: [],
    my_tiebreaker_guess: null,
    tiebreaker_leaderboard: [],
  } as GameState;

  const guessingState = {
    ...finishedState,
    phase: 'GUESSING',
    players: [
      { id: 'player-1', number: 1, name: 'Host', ready: true, connected: true },
      { id: 'player-2', number: 2, name: 'Writer', ready: true, connected: true },
      { id: 'player-3', number: 3, name: 'Subject', ready: true, connected: true },
      { id: 'player-4', number: 4, name: 'Friend', ready: true, connected: true },
    ],
    active_description_id: 'description-1',
    round_started_at: '2026-01-01T12:00:00Z',
    round_deadline: '2026-01-01T12:01:00Z',
    active_description: {
      id: 'description-1',
      sequence: 0,
      text: 'A true little story',
      author_id: 'player-2',
      subject_id: 'player-3',
      is_author: false,
      resolved: false,
      guesses: [],
    },
    my_guess: null,
    progress: { writing_submitted: 4, guess_submitted: 0, guess_required: 3 },
  } as GameState;

  it('lets a fully ready five-player Full Experience lobby start with empty seats', () => {
    const state = {
      ...finishedState,
      phase: 'LOBBY',
      game_mode: 'FULL_EXPERIENCE_8',
      player_capacity: 8,
      minimum_players: 5,
      player_count: 5,
      round_count: 20,
      round_duration_seconds: 30,
      players: Array.from({ length: 5 }, (_, index) => ({
        id: `player-${index + 1}`,
        number: index + 1,
        name: `Player ${index + 1}`,
        ready: true,
        connected: true,
      })),
    } as GameState;
    render(<Lobby state={state} act={vi.fn()} onCopy={vi.fn()} copied={false} />);
    expect(screen.getByText('5 OF 8 JOINED')).toBeInTheDocument();
    expect(screen.getByText('5/8 ready')).toBeInTheDocument();
    expect(screen.getAllByText('OPEN SEAT')).toHaveLength(3);
    expect(screen.getByRole('button', { name: /start the game/i })).toBeEnabled();
    expect(screen.getByText('Play with 5–8 players. Everyone describes every other player.')).toBeInTheDocument();
    expect(screen.getByText('ROUND TIMER: 30 SECONDS (FIXED)')).toBeInTheDocument();
  });

  it('uses the locked five-player roster and dynamic round count in Full Experience', () => {
    const fullExperienceState = {
      ...guessingState,
      game_mode: 'FULL_EXPERIENCE_8',
      player_capacity: 8,
      minimum_players: 5,
      player_count: 5,
      round_count: 20,
      players: [
        ...guessingState.players,
        { id: 'player-5', number: 5, name: 'Fifth', ready: true, connected: true },
      ],
      active_description: {
        ...guessingState.active_description!,
        sequence: 3,
      },
      progress: { writing_submitted: 5, guess_submitted: 0, guess_required: 4 },
    } as GameState;
    render(<Guessing state={fullExperienceState} act={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByText('ROUND 4 OF 20')).toBeInTheDocument();
    const authors = within(screen.getByRole('group', { name: 'Choose the author' }));
    expect(authors.getAllByRole('button')).toHaveLength(4);
    expect(authors.queryByRole('button', { name: /Host/ })).not.toBeInTheDocument();
    expect(authors.getByRole('button', { name: /Fifth/ })).toBeInTheDocument();
    const subjects = within(screen.getByRole('group', { name: 'Choose the subject' }));
    expect(subjects.getAllByRole('button')).toHaveLength(5);
    expect(subjects.getByRole('button', { name: /Host/ })).toBeInTheDocument();
    expect(subjects.getByRole('button', { name: /Writer/ })).toBeInTheDocument();
    fireEvent.click(authors.getByRole('button', { name: /Fifth/ }));
    fireEvent.click(subjects.getByRole('button', { name: /Fifth/ }));
    expect(authors.getByRole('button', { name: /Fifth/ })).toHaveAttribute('aria-pressed', 'true');
    expect(subjects.getByRole('button', { name: /Fifth/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('submits one valid guess only after the slider is completed', async () => {
    const lockedState = { ...guessingState, my_guess: { author_guess_id: 'player-3', subject_guess_id: null } };
    const act = vi.fn().mockResolvedValue(lockedState);
    const { rerender } = render(<Guessing state={guessingState} act={act} onError={vi.fn()} />);

    const slider = screen.getByRole('slider', { name: 'Slide to lock your guess' });
    expect(slider).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(within(screen.getByRole('group', { name: 'Choose the subject' })).getByRole('button', { name: /Subject/ }));
    expect(slider).not.toHaveAttribute('aria-disabled', 'true');
    expect(act).not.toHaveBeenCalled();

    fireEvent.keyDown(slider, { key: 'End' });
    await waitFor(() => expect(act).toHaveBeenCalledTimes(1));
    expect(act).toHaveBeenCalledWith('/guesses', {
      description_id: 'description-1',
      author_guess_id: null,
      subject_guess_id: 'player-3',
    });
    rerender(<Guessing state={lockedState} act={act} onError={vi.fn()} />);
    await waitFor(() => expect(slider).toHaveAttribute('aria-disabled', 'true'));
  });

  it('surfaces guess submission errors and leaves the selection available for retry', async () => {
    const act = vi.fn().mockRejectedValue(new Error('Guess request failed'));
    const onError = vi.fn();
    render(<Guessing state={guessingState} act={act} onError={onError} />);
    const subjectChoice = within(screen.getByRole('group', { name: 'Choose the subject' })).getByRole('button', { name: /Subject/ });
    fireEvent.click(subjectChoice);

    const slider = screen.getByRole('slider', { name: 'Slide to lock your guess' });
    fireEvent.keyDown(slider, { key: 'End' });
    await waitFor(() => expect(act).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Guess request failed'));
    expect(subjectChoice).toHaveAttribute('aria-pressed', 'true');
    expect(slider).not.toHaveAttribute('aria-disabled', 'true');
  });

  describe('final results actions', () => {
    it('shows descriptions in accessible flip cards and flips them with the keyboard', () => {
      const stateWithDescription = {
        ...finishedState,
        descriptions: [{
          id: 'description-1',
          sequence: 0,
          text: 'A true little story',
          author_id: 'player-1',
          subject_id: 'player-1',
          is_author: false,
          resolved: true,
          guesses: [],
        }],
      } as GameState;
      render(<Results state={stateWithDescription} act={vi.fn()} onNew={vi.fn()} onClosed={vi.fn()} onError={vi.fn()} />);

      const card = screen.getByRole('button', { name: /description 01, description 01/i });
      expect(card).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('A true little story')).toBeInTheDocument();

      fireEvent.keyDown(card, { key: ' ' });
      expect(card).toHaveAttribute('aria-pressed', 'false');
      expect(card.querySelector('.flip-card__face--back')).toHaveAttribute('aria-hidden', 'true');

      fireEvent.keyDown(card, { key: 'Enter' });
      expect(card).toHaveAttribute('aria-pressed', 'true');
    });

    it('shows an export failure to the player', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Results are unavailable' }),
      }));
      const onError = vi.fn();
      render(<Results state={finishedState} act={vi.fn()} onNew={vi.fn()} onClosed={vi.fn()} onError={onError} />);

      fireEvent.click(screen.getByRole('button', { name: /download results/i }));
      await waitFor(() => expect(onError).toHaveBeenCalledWith('Results are unavailable'));
      vi.unstubAllGlobals();
    });

    it('confirms closure and surfaces a backend deletion failure', async () => {
      const onError = vi.fn();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Could not delete match data; retry safely' }),
      }));
      render(<Results state={finishedState} act={vi.fn()} onNew={vi.fn()} onClosed={vi.fn()} onError={onError} />);

      fireEvent.click(screen.getAllByRole('button', { name: 'Close Match Room' })[0]);
      expect(screen.getByText(/permanently deletes its game data/i)).toBeInTheDocument();
      fireEvent.click(screen.getAllByRole('button', { name: 'Close Match Room' })[1]);
      await waitFor(() => expect(onError).toHaveBeenCalledWith('Could not delete match data; retry safely'));
      vi.unstubAllGlobals();
    });
  });

  describe('author-identification tiebreaker', () => {
    const players = [
      { id: 'player-1', number: 1, name: 'Alex', ready: true, connected: true },
      { id: 'player-2', number: 2, name: 'Blair', ready: true, connected: true },
      { id: 'player-3', number: 3, name: 'Casey', ready: true, connected: true },
      { id: 'player-4', number: 4, name: 'Drew', ready: true, connected: true },
    ];

    const tieGuessingState = (meId: string, isAuthor = false): GameState => ({
      ...({
        game_id: 'game-1',
        code: 'AB12CD',
        phase: 'TIEBREAKER',
        version: 5,
        game_mode: 'CLASSIC',
        player_capacity: 4,
        minimum_players: 4,
        player_count: 4,
        round_count: 12,
        round_duration_seconds: 60,
        round_started_at: '2026-01-01T12:00:00Z',
        round_deadline: '2026-01-01T12:01:00Z',
        server_now: '2026-01-01T12:00:00Z',
        host_id: 'player-1',
        me: players.find((player) => player.id === meId)!,
        players,
        active_description_id: null,
        active_description: null,
        descriptions: [],
        drafts: [],
        my_guess: null,
        progress: { writing_submitted: 4, guess_submitted: 0, guess_required: 0 },
        leaderboard: players.map((player) => ({ ...player, author_points: 0, subject_points: 0, tiebreaker_points: 0, total: 0 })),
        winners: [],
        tie_accepted: false,
        tie_completed: false,
        tie_available: false,
        tie_stage: 'GUESSING',
        tie_participants: ['player-1', 'player-2'],
        tiebreaker_progress: { description_submitted: 6, description_required: 6, guess_submitted: 1, guess_required: 3, waiting_player_ids: ['player-1', 'player-2'] },
        tiebreaker_submitted: true,
        active_tiebreaker: {
          id: 'tie-description-1',
          sequence: 0,
          text: 'You always know the best local coffee spot.',
          author_id: null,
          subject_id: 'player-4',
          is_author: isAuthor,
          resolved: false,
          guesses: [],
        },
        tiebreaker_prompts: [],
        my_tiebreaker_guess: null,
        tiebreaker_leaderboard: [],
      } as GameState),
      me: players.find((player) => player.id === meId)!,
    });

    it('shows the subject and only tied players as author options to a non-tied guesser', async () => {
      const state = tieGuessingState('player-3');
      const act = vi.fn().mockResolvedValue(state);
      render(<Tiebreaker state={state} act={act} />);

      expect(screen.getByText('ABOUT')).toBeInTheDocument();
      expect(screen.getByText('Player 4 — Drew')).toBeInTheDocument();
      expect(screen.getByText('WHO WROTE THIS DESCRIPTION?')).toBeInTheDocument();
      expect(screen.getByText('You always know the best local coffee spot.')).toBeInTheDocument();
      const options = within(screen.getByRole('group', { name: 'Choose which tied player wrote this description' }));
      expect(options.getAllByRole('button')).toHaveLength(2);
      expect(options.getByRole('button', { name: /Alex/ })).toBeInTheDocument();
      expect(options.getByRole('button', { name: /Blair/ })).toBeInTheDocument();
      expect(options.queryByRole('button', { name: /Casey|Drew/ })).not.toBeInTheDocument();

      fireEvent.click(options.getByRole('button', { name: /Alex/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Lock Guess' }));
      await waitFor(() => expect(act).toHaveBeenCalledWith('/tiebreaker/guess', {
        prompt_id: 'tie-description-1',
        author_guess_id: 'player-1',
      }));
    });

    it('lets a tied player guess another tied author but makes the current author sit out', () => {
      const state = tieGuessingState('player-2');
      const { rerender } = render(<Tiebreaker state={state} act={vi.fn()} />);
      expect(within(screen.getByRole('group', { name: 'Choose which tied player wrote this description' })).getAllByRole('button')).toHaveLength(1);
      expect(screen.getByRole('button', { name: /Alex/ })).toBeInTheDocument();

      rerender(<Tiebreaker state={tieGuessingState('player-1', true)} act={vi.fn()} />);
      expect(screen.getByText('You wrote this description.')).toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Choose which tied player wrote this description' })).not.toBeInTheDocument();
    });
  });
});
