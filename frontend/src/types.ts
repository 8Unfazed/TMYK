export type Phase = 'LOBBY' | 'WRITING' | 'GUESSING' | 'REVEAL' | 'TIEBREAKER' | 'FINISHED' | 'CLOSING' | 'CANCELLED';
export type GameMode = 'CLASSIC' | 'FULL_EXPERIENCE_8';

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
  subject_id: string | null;
  is_author: boolean;
  resolved: boolean;
  guesses: { guesser_id: string; guesser_name: string; author_guess_id: string | null; points: number; timed_out: boolean }[];
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
  game_mode: GameMode;
  player_capacity: 4 | 8;
  minimum_players: 4 | 5;
  player_count: number;
  round_count: number;
  round_duration_seconds: 30 | 60 | 90 | 120;
  round_started_at: string | null;
  round_deadline: string | null;
  server_now: string;
  host_id: string;
  me: { id: string; number: number; name: string };
  players: Player[];
  active_description_id: string | null;
  active_description: Description | null;
  descriptions: Description[];
  drafts: { subject_id: string; text: string }[];
  my_guess: { author_guess_id: string | null; subject_guess_id: string | null; timed_out?: boolean } | null;
  progress: { writing_submitted: number; guess_submitted: number; guess_required: number };
  leaderboard: { id: string; number: number; name: string; author_points: number; subject_points: number; tiebreaker_points: number; total: number }[];
  winners: string[];
  tie_accepted: boolean;
  tie_completed: boolean;
  tie_available: boolean;
  tie_stage: 'WRITING' | 'GUESSING' | 'REVEAL' | null;
  tie_participants: string[];
  tiebreaker_progress: { description_submitted: number; description_required: number; guess_submitted: number; guess_required: number; waiting_player_ids: string[] };
  tiebreaker_submitted: boolean;
  active_tiebreaker: TiebreakerPrompt | null;
  tiebreaker_prompts: TiebreakerPrompt[];
  my_tiebreaker_guess: { author_guess_id: string | null; timed_out: boolean } | null;
  tiebreaker_leaderboard: { id: string; number: number; name: string; author_points: number; subject_points: number; tiebreaker_points: number; total: number }[];
}
