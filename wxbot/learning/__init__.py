"""Learning from past predictions (v2 M9): spec sections 13 to 15.

    outcomes.py  the ledger: every resolved market's prediction, inputs, market
                 price, decision and result, with its error class
    params.py    versioned station bias/spread parameter sets (one in production)
    retrain.py   periodic retraining, out-of-sample approval, deploy, rollback

The cycle's learning step records new outcomes, checks whether a newly
deployed set should be rolled back, and retrains when due. The probability
calibrators (wxbot/calibration/) are refitted by their own step with their own
approval rule, each on the predictions of one param set only.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import desc, func, select

from wxbot.db import Database, prediction_outcomes, system_events
from wxbot.learning import outcomes, params, retrain

EVENT_CODES = ("MODEL_RETRAINED", "MODEL_DEPLOYED", "MODEL_ROLLBACK", "SIGNIFICANT_MODEL_ERROR")
SET_FIELDS = ("version", "status", "origin", "created_at", "train_from", "train_to", "train_days", "n_rows",
              "n_carried", "evaluation", "approved", "reason", "deployed_at", "retired_at", "replaces")


def learn(db: Database, cfg, history, observer, now: datetime) -> dict:
    out = {"outcomes": outcomes.record(db, now), "rollback": retrain.check_rollback(db, cfg, now)}
    out["retrain"] = retrain.retrain(db, cfg, history, observer, now)
    return out


def _state(db: Database, key: str):
    raw = db.get_state(key)
    return json.loads(raw) if raw and raw.startswith("{") else raw


def summary(db: Database, limit: int = 20) -> dict:
    """Model updates for the dashboard and the report: the param sets, newest
    first, the last retraining and rollback check, and the learning events."""
    ev = system_events.c
    prod = params.production(db)
    return {
        "production": prod and {k: prod[k] for k in SET_FIELDS},
        "sets": [{k: ps[k] for k in SET_FIELDS} for ps in params.history(db, limit)],
        "last_retrain": _state(db, "last_retrain"), "next_retrain": db.get_state("next_retrain_at"),
        "last_rollback_check": _state(db, "last_rollback_check"),
        "ledger_rows": db.agg(select(func.count().label("n")).select_from(prediction_outcomes))["n"],
        "events": db.rows(select(ev.ts, ev.level, ev.code, ev.message).where(ev.code.in_(EVENT_CODES))
                          .order_by(desc(ev.id)).limit(limit)),
    }
