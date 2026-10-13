/** [selection, probability, is_pick (0/1), confidence tier (0 High, 1 Medium, 2 Low)] */
export type Sel = [string, number, number, number];
/** line key ('null' for markets without a line) -> selections */
export type LinesMap = Record<string, Sel[]>;

export interface MarketMeta {
	name: string;
	family: 'A' | 'B' | 'C' | 'D' | 'E';
	exclusive: boolean;
	order: number;
}

export interface Ctx {
	home: string;
	away: string;
}

export interface MatchContext {
	lambda_home?: number;
	lambda_away?: number;
	matches_used?: number;
	n_sims?: number;
	first_half_goal_share?: number;
}

export interface FixtureSummary {
	id: number;
	league: string;
	kickoff: string;
	home: string;
	away: string;
	p: { home: number; draw: number; away: number };
	tiers: Record<string, number>;
}

export interface FormResult {
	date: string;
	opponent: string;
	home: boolean;
	gf: number;
	ga: number;
	result: 'W' | 'D' | 'L';
}

export interface Meeting {
	date: string;
	home: string;
	away: string;
	ft_home: number;
	ft_away: number;
}

export interface MatchDetail {
	id: number;
	league: string;
	kickoff: string;
	home: string;
	away: string;
	p: { home: number; draw: number; away: number };
	ctx: MatchContext;
	preds: Record<string, LinesMap>;
	form: { home: FormResult[]; away: FormResult[] };
	h2h: Meeting[];
}

export interface CalibrationPoint {
	from: number;
	to: number;
	n: number;
	predicted: number;
	actual: number;
}

export interface TierRow {
	tier: string;
	share: number;
	predicted: number;
	happened: number;
	skill: number;
}

export interface LiveMatch {
	league: string;
	date: string;
	home: string;
	away: string;
	score: [number, number];
	p: { home: number; draw: number; away: number };
	pick: 'home' | 'draw' | 'away';
	hit: number;
}

export interface Rate {
	n: number;
	predicted: number | null;
	actual: number | null;
}

export interface Live {
	n: number;
	matches: LiveMatch[];
	log_loss: number;
	log_loss_base: number;
	pick_hits: number;
	home: Rate;
	draw: Rate;
	away: Rate;
	btts_yes: Rate;
	over25: Rate;
	calibration: { from: number; n: number; predicted: number; actual: number }[];
	selections: number;
	waiting_minutes: number;
	model_version: string;
}

export interface Index {
	generated_at: string;
	model_version: string;
	leagues: Record<string, string>;
	markets: Record<string, MarketMeta>;
	fixtures: FixtureSummary[];
	validation: {
		calibration: CalibrationPoint[];
		families: { family: string; selections: number; model: number; base: number; skill: number }[];
		leagues: { id: string; name: string; matches: number; model: number; base: number; book: number; right_model: number; right_book: number }[];
	};
	live: Live;
	confidence: {
		labels: string[];
		validation: { fitted_on_matches: number; checked_on_matches: number; until: string; tiers: TierRow[] } | null;
		backtest: { matches: number; from: string; to: string; selections: number } | null;
	};
}
