export type Phase = 'LOBBY' | 'WRITING' | 'GUESSING' | 'REVEAL' | 'TIEBREAKER' | 'FINISHED' | 'CLOSING' | 'CANCELLED';

export interface Player {
  id: string;
  number: number;
  name: string;
  ready: boolean;
  connected: boolean;
  writing_submitted?: boolean;
}

export interface GuessReveal {
  guesser_id: string;
  guesser_name: string;
  guesser_number: number;
  author_guess_id: string | null;
  subject_guess_id: string | null;
  author_points: number;
  subject_points: number;
}

export interface TiebreakerPrompt {
  id: string;
  sequence: number | null;
  text: string | null;
  author_id: string | null;
  is_author: boolean;
  resolved: boolean;
  guesses: { guesser_id: string; guesser_name: string; author_guess_id: string; points: number }[];
}

export interface Description {
  id: string;
  sequence: number | null;
  text: string | null;
  author_id: string | null;
  subject_id: string | null;
  is_author: boolean;
  resolved: boolean;
  guesses: GuessReveal[];
}

export interface GameState {
  game_id: string;
  code: string;
  phase: Phase;
  version: number;
  host_id: string;
  me: { id: string; number: number; name: string };
  players: Player[];
  active_description_id: string | null;
  active_description: Description | null;
  descriptions: Description[];
  drafts: { subject_id: string; text: string }[];
  my_guess: { author_guess_id: string | null; subject_guess_id: string | null } | null;
  progress: { writing_submitted: number; guess_submitted: number; guess_required: number };
  leaderboard: { id: string; number: number; name: string; author_points: number; subject_points: number; tiebreaker_points: number; total: number }[];
  winners: string[];
  tie_accepted: boolean;
  tie_completed: boolean;
  tie_available: boolean;
  tie_stage: 'WRITING' | 'GUESSING' | 'REVEAL' | null;
  tie_participants: string[];
  tiebreaker_progress: { clue_submitted: number; clue_required: number; guess_submitted: number; guess_required: number };
  tiebreaker_draft: string | null;
  active_tiebreaker: TiebreakerPrompt | null;
  tiebreaker_prompts: TiebreakerPrompt[];
  my_tiebreaker_guess: { author_guess_id: string } | null;
}
