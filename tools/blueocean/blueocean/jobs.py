"""抽出条件を保存して、毎回同じ条件で回す。

これまで抽出は「そのつどコマンドを打つ」ものだった。だから

    どんな条件で抜いたのか、次に思い出せない
    条件を1文字変えるだけで、前回と比較できなくなる
    週次で回そうとすると、長いコマンドを毎回組み立てることになる

条件をファイルに固定すれば、この3つが同時に消える。
**同じ条件で回すからこそ、前回との差分が意味を持つ。**

    {
      "name": "anime-set",
      "label": "アニメ・フィギュアのまとめ売り",
      "market": "ebay_us",
      "target_margin": 0.20,
      "scan":   {"genre": "anime_figure", "mode": "set", "limit": 40,
                 "assume": {"weight_g": 1100, "length_cm": 32,
                            "width_cm": 24, "height_cm": 18},
                 "out": "out/anime-candidates.csv", "sheet": "out/anime-hunt.html"},
      "judge":  {"candidates": "data/anime.csv", "history": "data/history.jsonl",
                 "out": "out/anime-plan.csv", "sheet": "out/anime-plan.html",
                 "refresh": true}
    }

``scan`` は「何を探すか」を決める工程、``judge`` は「買っていいか」を決める工程。
片方だけの定義でもよい。両方あるときは scan → judge の順に走る。

判定の結果は履歴に追記されるので、2回目以降は**前回からの変化だけ**が出る。
週次で同じジョブを回すのが想定した使い方。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .discovery import (
    GENRES,
    Mode,
    ScanPolicy,
    load_genres,
    load_keywords,
    scan_all,
    scan_genre,
    write_candidate_template,
)
from .history import Change
from .models import Market, SellerLevel, TaxProfile
from .pipeline import load_candidates, run_axis1_with_history, write_listing_plan
from .profit import DEFAULT_PROFILES
from .scoring import ScoringPolicy
from .shipping import Carrier, Parcel, load_rate_table_csv
from .sources.base import MarketDataSource


class JobError(ValueError):
    """設定の誤り。黙って既定値で走らせると、間違った条件で抽出し続けることになる。"""


@dataclass(frozen=True)
class Job:
    """1つの抽出条件。"""
    name: str
    label: str = ""
    market: str = "ebay_us"
    level: str = "above_standard"
    target_margin: float = 0.20
    fx_jpy_per_usd: float = 150.0
    taxable: bool = True
    carrier: str | None = None
    rates: str | None = None
    genre_file: str | None = None
    scan: dict[str, Any] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.label or self.name

    def policy(self) -> ScoringPolicy:
        return ScoringPolicy(
            target_margin=self.target_margin,
            fx_jpy_per_usd=self.fx_jpy_per_usd,
            carrier=Carrier(self.carrier) if self.carrier else None,
            rate_tables=load_rate_table_csv(self.rates) if self.rates else None,
        )

    def common(self) -> dict[str, Any]:
        return dict(
            level=SellerLevel(self.level),
            tax=TaxProfile(is_taxable_entity=self.taxable),
        )


def load_jobs(path: str | Path) -> dict[str, Job]:
    """ジョブ定義を読む。1件でも複数件でも受け付ける。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    items = raw if isinstance(raw, list) else [raw] if "name" in raw else list(raw.values())
    if isinstance(raw, dict) and "name" not in raw:
        # {"anime-set": {...}} 形式では、キーを name として採用する
        items = [{**v, "name": v.get("name", k)} for k, v in raw.items()]
    out: dict[str, Job] = {}
    for it in items:
        if "name" not in it:
            raise JobError("ジョブに name がありません")
        known = {f for f in Job.__dataclass_fields__}
        unknown = set(it) - known
        if unknown:
            # 綴り違いを黙って無視すると、意図と違う条件で抽出し続けることになる
            raise JobError(
                f"ジョブ {it['name']}：知らない項目 {sorted(unknown)}。"
                f"使えるのは {sorted(known)}"
            )
        out[it["name"]] = Job(**it)
    return out


@dataclass
class JobResult:
    """1回の実行の結果。何を書いたかを必ず返す。"""
    job: Job
    scanned: int = 0
    hunt_worthy: int = 0
    judged: int = 0
    listable: int = 0
    changes: list[Change] = field(default_factory=list)
    stale_warning: str | None = None
    written: list[str] = field(default_factory=list)

    @property
    def actionable_changes(self) -> list[Change]:
        return [c for c in self.changes if c.is_actionable]


def _parcel(d: dict[str, Any] | None) -> Parcel:
    d = d or {}
    return Parcel(int(d.get("weight_g", 500)), float(d.get("length_cm", 0)),
                  float(d.get("width_cm", 0)), float(d.get("height_cm", 0)))


def run_job(
    job: Job,
    source: MarketDataSource,
    *,
    today: date | None = None,
    record: bool = True,
) -> JobResult:
    """ジョブを1回走らせる。scan → judge の順。"""
    res = JobResult(job=job)
    profile = DEFAULT_PROFILES[Market(job.market)]
    policy = job.policy()

    if job.scan:
        sc = job.scan
        if sc.get("genre"):
            genres = dict(GENRES)
            if job.genre_file:
                genres.update(load_genres(job.genre_file))
            if sc["genre"] not in genres:
                raise JobError(f"ジャンル {sc['genre']} は未定義です")
            report = scan_genre(
                genres[sc["genre"]], source, profile,
                ScanPolicy.from_scoring(policy),
                mode=Mode(sc.get("mode", "both")), limit=sc.get("limit"),
                assume=_parcel(sc.get("assume")), **job.common(),
            )
            results = report.results
        else:
            kws = sc.get("keywords") or (
                load_keywords(sc["keywords_file"]) if sc.get("keywords_file") else []
            )
            if not kws:
                raise JobError(f"ジョブ {job.name}：scan に genre / keywords / "
                               f"keywords_file のいずれかが要ります")
            results = scan_all(kws, source, profile, ScanPolicy.from_scoring(policy),
                               assume=_parcel(sc.get("assume")), **job.common())
        res.scanned = len(results)
        res.hunt_worthy = sum(1 for r in results if r.is_hunt_worthy)

        if sc.get("out"):
            Path(sc["out"]).parent.mkdir(parents=True, exist_ok=True)
            write_candidate_template(results, sc["out"])
            res.written.append(sc["out"])
        if sc.get("sheet"):
            from .contactsheet import from_scan, write as write_sheet

            Path(sc["sheet"]).parent.mkdir(parents=True, exist_ok=True)
            write_sheet(
                from_scan(results), sc["sheet"],
                title=f"{job.title}：探しに行く型番",
                note="予算を超える値札はその場で見送れます。写真と見比べてから買ってください。",
            )
            res.written.append(sc["sheet"])

    if job.judge:
        jd = job.judge
        if not jd.get("candidates"):
            raise JobError(f"ジョブ {job.name}：judge に candidates が要ります")
        cands = load_candidates(jd["candidates"])
        kw = dict(market=Market(job.market), policy=policy, refresh=bool(jd.get("refresh")),
                  **job.common())
        if jd.get("history"):
            scored, res.changes, res.stale_warning = run_axis1_with_history(
                cands, source, jd["history"], today=today, record=record, **kw
            )
        else:
            from .pipeline import run_axis1

            scored = run_axis1(cands, source, **kw)
        res.judged = len(scored)

        if jd.get("out"):
            Path(jd["out"]).parent.mkdir(parents=True, exist_ok=True)
            res.listable = write_listing_plan(scored, jd["out"])
            res.written.append(jd["out"])
        if jd.get("sheet"):
            from .contactsheet import from_scored, write as write_sheet

            Path(jd["sheet"]).parent.mkdir(parents=True, exist_ok=True)
            write_sheet(
                from_scored(scored), jd["sheet"],
                title=f"{job.title}：出品候補",
                note="国内で探すときに、この写真と見比べてください。型番が同じでも世代違いがあります。",
            )
            res.written.append(jd["sheet"])

    return res
