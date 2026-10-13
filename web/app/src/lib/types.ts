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
	has_odds: boolean;
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

export interface OddsRow {
	selection: string;
	p: number;
	tier: number;
	fair: number;
	avg_odds: number;
	best_odds: number;
	edge: number;
	ev: number | null;
}
export interface OddsMarket {
	market: string;
	line: number | null;
	margin: number;
	stake_can_be_returned: boolean;
	rows: OddsRow[];
}
export interface OddsBlock {
	fetched_at: string;
	source: string;
	markets: OddsMarket[];
}

export interface BacktestRoi {
	timing: 'opening' | 'closing';
	group: string;
	min_edge: number;
	price: 'average' | 'best';
	bets: number;
	hit_rate: number;
	avg_odds: number;
	roi: number;
	roi_ci: number | null;
}
export interface BlendResult {
	matches: number;
	checked_on: number;
	market: number;
	model: number;
	blend: number;
	weight_market: number;
	weight_model: number;
}
export interface ValueBacktest {
	period: { from: string; to: string; matches: number };
	information: Record<'opening' | 'closing', Record<'1x2' | 'ou25', BlendResult>>;
	back_everything: { timing: 'opening' | 'closing'; price: 'average' | 'best'; bets: number; roi: number }[];
	roi: BacktestRoi[];
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
	odds: OddsBlock | null;
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
	value_backtest: ValueBacktest | null;
	confidence: {
		labels: string[];
		validation: { fitted_on_matches: number; checked_on_matches: number; until: string; tiers: TierRow[] } | null;
		backtest: { matches: number; from: string; to: string; selections: number } | null;
	};
}
