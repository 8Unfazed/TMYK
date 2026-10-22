import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import App, { Results } from './App';
import { GameState } from './types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
    tiebreaker_progress: { clue_submitted: 0, clue_required: 0, guess_submitted: 0, guess_required: 0 },
    tiebreaker_draft: null,
    active_tiebreaker: null,
    tiebreaker_prompts: [],
    my_tiebreaker_guess: null,
  } as GameState;

  describe('final results actions', () => {
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
});
