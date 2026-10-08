"""Scoring rules and small helpers shared by backtests."""
import numpy as np

EPS = 1e-12


def result_probs(p: np.ndarray) -> tuple[float, float, float]:
    """(home win, draw, away win) from a scoreline matrix P[home_goals, away_goals]."""
    return float(np.tril(p, -1).sum()), float(np.trace(p)), float(np.triu(p, 1).sum())


def over_probability(p: np.ndarray, line: float) -> float:
    """P(total goals > line) for a half line such as 2.5."""
    total = np.add.outer(np.arange(p.shape[0]), np.arange(p.shape[1]))
    return float(p[total > line].sum())


def btts_probability(p: np.ndarray) -> float:
    return float(p[1:, 1:].sum())


def demargin(odds: np.ndarray) -> np.ndarray:
    """Proportional de-margin of decimal odds along the last axis: implied probabilities that sum to 1."""
    inv = 1.0 / np.asarray(odds, dtype=float)
    return inv / inv.sum(axis=-1, keepdims=True)


def log_loss(probs: np.ndarray, outcome: np.ndarray) -> float:
    """Mean negative log probability given to what happened. probs: (n, k); outcome: (n,) class index."""
    p = np.clip(probs[np.arange(len(outcome)), outcome], EPS, 1)
    return float(-np.log(p).mean())


def brier(probs: np.ndarray, outcome: np.ndarray) -> float:
    """Multi-class Brier score: mean over matches of the sum of squared errors across outcomes."""
    onehot = np.eye(probs.shape[1])[outcome]
    return float(((probs - onehot) ** 2).sum(axis=1).mean())


def rps(probs: np.ndarray, outcome: np.ndarray) -> float:
    """Ranked probability score for ordered outcomes (home, draw, away). Lower is better."""
    onehot = np.eye(probs.shape[1])[outcome]
    cum = np.cumsum(probs, axis=1)[:, :-1] - np.cumsum(onehot, axis=1)[:, :-1]
    return float((cum**2).sum(axis=1).mean() / (probs.shape[1] - 1))
