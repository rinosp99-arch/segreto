"""SUPER API v1 - A/B TESTING INFRASTRUCTURE.

Targets: cta | headline | cover | photo | model_order | teaser | button_placement | timer.
Deterministic assignment (hash of session_id + experiment_id, weighted).
Results with two-proportion z-test. A winner is NEVER chosen automatically: `conclude`
requires an explicit winner and enough data (or force=true by a human).
"""
import math
import uuid
import hashlib
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from database import experiments_col, exposures_col, events_col, now_iso, serialize_doc
from v1_security import require, actor_of, request_id_of, rate_limit, DEFAULT_LIMIT_PUBLIC
from v1_versioning import record_version, audit_log
from v1_tracking import CANONICAL_TO_LEGACY

experiments_router = APIRouter(prefix="/api/v1/experiments", tags=["A/B Testing"])

TARGETS = ["cta", "headline", "cover", "photo", "model_order", "teaser", "button_placement", "timer"]


class Variant(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: Optional[str] = None
    nome: str
    value: Any = None       # e.g. CTA text, image url, timer seconds, list of slugs
    weight: float = 1.0


class ExperimentIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nome: str
    target_type: str
    scope: Dict[str, Any] = Field(default_factory=lambda: {"kind": "global"})  # {kind: global|model|landing, id}
    variants: List[Variant]
    metric: str = "onlyfans_click"
    min_sample_per_variant: int = 200
    confidence: float = 0.95
    note: str = ""


def _enrich(doc: dict) -> dict:
    return serialize_doc(doc)


def _z_p(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return None
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0
    if se == 0:
        return None
    z = (p1 - p2) / se
    # two-tailed p-value via erf
    pval = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return {"z": round(z, 3), "p_value": round(pval, 4)}


async def experiment_results(exp: dict) -> dict:
    metric = exp.get("metric", "onlyfans_click")
    legacy = CANONICAL_TO_LEGACY.get(metric, metric)
    rows = []
    for v in exp.get("variants", []):
        exposures = await exposures_col.count_documents({"experiment_id": exp["id"], "variant_id": v["id"]})
        sessions = [e["session_id"] async for e in exposures_col.find({"experiment_id": exp["id"], "variant_id": v["id"]}, {"_id": 0, "session_id": 1})]
        conv = 0
        if sessions:
            q: Dict[str, Any] = {"session_id": {"$in": sessions}, "$or": [{"event": metric}, {"tipo": legacy}]}
            if exp.get("started_at"):
                q["timestamp"] = {"$gte": exp["started_at"]}
            sc = exp.get("scope") or {}
            if sc.get("kind") == "model" and sc.get("id"):
                q["model_id"] = sc["id"]
            r = await events_col.aggregate([{"$match": q}, {"$group": {"_id": "$session_id"}}, {"$count": "n"}]).to_list(1)
            conv = r[0]["n"] if r else 0
        rows.append({"variant_id": v["id"], "nome": v["nome"], "value": v.get("value"), "exposures": exposures, "conversions": conv,
                     "rate": round(conv / exposures * 100, 2) if exposures else 0.0})
    min_n = int(exp.get("min_sample_per_variant", 200))
    enough = all(r["exposures"] >= min_n for r in rows) and len(rows) >= 2
    stats = None
    leader = max(rows, key=lambda r: r["rate"]) if rows else None
    if len(rows) >= 2 and leader:
        others = [r for r in rows if r["variant_id"] != leader["variant_id"]]
        runner = max(others, key=lambda r: r["rate"])
        stats = _z_p(leader["rate"] / 100, leader["exposures"], runner["rate"] / 100, runner["exposures"])
    alpha = 1 - float(exp.get("confidence", 0.95))
    significant = bool(stats and stats["p_value"] is not None and stats["p_value"] < alpha and enough)
    if not enough:
        rec = f"Dati insufficienti: servono almeno {min_n} esposizioni per variante. Nessun vincitore."
    elif significant:
        rec = f"Differenza statisticamente significativa (p={stats['p_value']}). Variante in testa: {leader['nome']}. Il vincitore va confermato manualmente."
    else:
        rec = "Campione sufficiente ma differenza non significativa: continuare il test o concludere senza vincitore."
    return {"variants": rows, "enough_data": enough, "leader": leader["variant_id"] if leader else None, "stats": stats, "significant": significant, "recommendation": rec, "auto_winner": False}


# ---------------- ROUTES ----------------
@experiments_router.get("")
async def list_experiments(stato: Optional[str] = None, principal=Depends(require("experiments:read"))):
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if stato:
        q["stato"] = stato
    docs = await experiments_col.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": [_enrich(d) for d in docs], "targets": TARGETS}


@experiments_router.post("", status_code=201)
async def create_experiment(body: ExperimentIn, request: Request, principal=Depends(require("experiments:write"))):
    if body.target_type not in TARGETS:
        raise HTTPException(status_code=400, detail={"message": "target_type non valido", "targets": TARGETS})
    if len(body.variants) < 2:
        raise HTTPException(status_code=400, detail="Servono almeno 2 varianti")
    doc = body.model_dump()
    for v in doc["variants"]:
        v["id"] = v.get("id") or str(uuid.uuid4())[:8]
    doc.update({"id": str(uuid.uuid4()), "stato": "bozza", "winner_variant_id": None, "created_at": now_iso(), "updated_at": now_iso(), "created_by": actor_of(principal), "started_at": None, "ended_at": None})
    await experiments_col.insert_one(doc)
    await record_version("experiment", doc["id"], None, doc, actor_of(principal), source=principal.get("source", "manual"), reason="Creazione esperimento", request_id=request_id_of(request))
    return _enrich(doc)


@experiments_router.get("/{exp_id}")
async def get_experiment(exp_id: str, principal=Depends(require("experiments:read"))):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    out = _enrich(doc)
    out["results"] = await experiment_results(doc)
    return out


@experiments_router.patch("/{exp_id}")
async def patch_experiment(exp_id: str, body: Dict[str, Any], request: Request, principal=Depends(require("experiments:write"))):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    if doc.get("stato") == "attivo" and "variants" in body:
        raise HTTPException(status_code=409, detail="Non puoi cambiare le varianti di un test attivo (metti in pausa)")
    allowed = {"nome", "variants", "metric", "min_sample_per_variant", "confidence", "note", "scope"}
    upd = {k: v for k, v in body.items() if k in allowed}
    if "variants" in upd:
        for v in upd["variants"]:
            v["id"] = v.get("id") or str(uuid.uuid4())[:8]
    new_doc = {**doc, **upd, "updated_at": now_iso()}
    await experiments_col.replace_one({"id": exp_id}, new_doc)
    await record_version("experiment", exp_id, doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason="Aggiornamento esperimento", request_id=request_id_of(request))
    return _enrich(new_doc)


async def _set_state(exp_id: str, stato: str, principal: dict, request: Request, extra: Optional[dict] = None):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    new_doc = {**doc, "stato": stato, "updated_at": now_iso(), **(extra or {})}
    await experiments_col.replace_one({"id": exp_id}, new_doc)
    await record_version("experiment", exp_id, doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason=f"stato:{stato}", request_id=request_id_of(request))
    return _enrich(new_doc)


@experiments_router.post("/{exp_id}/start")
async def start(exp_id: str, request: Request, principal=Depends(require("experiments:write"))):
    return await _set_state(exp_id, "attivo", principal, request, {"started_at": now_iso()})


@experiments_router.post("/{exp_id}/pause")
async def pause(exp_id: str, request: Request, principal=Depends(require("experiments:write"))):
    return await _set_state(exp_id, "in_pausa", principal, request)


class ConcludeBody(BaseModel):
    winner_variant_id: Optional[str] = None
    force: bool = False


@experiments_router.post("/{exp_id}/conclude")
async def conclude(exp_id: str, body: ConcludeBody, request: Request, principal=Depends(require("experiments:write"))):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    res = await experiment_results(doc)
    if body.winner_variant_id:
        if not res["significant"] and not body.force:
            raise HTTPException(status_code=409, detail={"message": "Dati insufficienti o differenza non significativa: nessun vincitore automatico. Usa force=true solo con decisione umana consapevole.", "results": res})
        if body.winner_variant_id not in [v["id"] for v in doc["variants"]]:
            raise HTTPException(status_code=400, detail="Variante vincitrice inesistente")
    out = await _set_state(exp_id, "concluso", principal, request, {"ended_at": now_iso(), "winner_variant_id": body.winner_variant_id, "final_results": res, "concluded_by": actor_of(principal), "forced": body.force})
    await audit_log(actor_of(principal), "conclude", "experiment", exp_id, {"winner": body.winner_variant_id, "forced": body.force}, request_id_of(request))
    return out


@experiments_router.delete("/{exp_id}")
async def delete_experiment(exp_id: str, request: Request, principal=Depends(require("experiments:write"))):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    if doc.get("stato") == "attivo":
        raise HTTPException(status_code=409, detail="Metti in pausa o concludi il test prima di eliminarlo")
    new_doc = {**doc, "stato": "eliminato", "is_deleted": True, "deleted_at": now_iso()}
    await experiments_col.replace_one({"id": exp_id}, new_doc)
    await record_version("experiment", exp_id, doc, new_doc, actor_of(principal), source=principal.get("source", "manual"), reason="Soft delete", request_id=request_id_of(request))
    return {"ok": True, "soft_deleted": True}


@experiments_router.get("/{exp_id}/results")
async def results(exp_id: str, principal=Depends(require("experiments:read"))):
    doc = await experiments_col.find_one({"id": exp_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esperimento non trovato")
    return {"experiment_id": exp_id, "nome": doc["nome"], "stato": doc["stato"], **(await experiment_results(doc))}


# ---------------- PUBLIC: assignment + exposure ----------------
public_experiments_router = APIRouter(prefix="/api/experiments", tags=["A/B Testing"])


def _pick(exp: dict, session_id: str) -> dict:
    h = int(hashlib.sha256(f"{exp['id']}:{session_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    total = sum(float(v.get("weight", 1)) for v in exp["variants"]) or 1
    acc = 0.0
    for v in exp["variants"]:
        acc += float(v.get("weight", 1)) / total
        if h <= acc:
            return v
    return exp["variants"][-1]


@public_experiments_router.get("/assign")
async def assign(session_id: str, request: Request, model_id: Optional[str] = None, landing_id: Optional[str] = None):
    """Return active variants for this session (deterministic). Records exposure."""
    ip = request.client.host if request.client else "anon"
    rate_limit(f"pub:{ip}", DEFAULT_LIMIT_PUBLIC)
    if not session_id:
        return {"assignments": []}
    out = []
    async for exp in experiments_col.find({"stato": "attivo"}, {"_id": 0}):
        sc = exp.get("scope") or {"kind": "global"}
        if sc.get("kind") == "model" and sc.get("id") != model_id:
            continue
        if sc.get("kind") == "landing" and sc.get("id") != landing_id:
            continue
        v = _pick(exp, session_id)
        try:
            await exposures_col.insert_one({"experiment_id": exp["id"], "session_id": session_id, "variant_id": v["id"], "timestamp": now_iso(), "model_id": model_id, "landing_id": landing_id})
        except Exception:
            pass  # already exposed
        out.append({"experiment_id": exp["id"], "target_type": exp["target_type"], "variant_id": v["id"], "value": v.get("value")})
    return {"assignments": out}
