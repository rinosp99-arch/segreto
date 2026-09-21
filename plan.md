# Plan — SEO Autopilot FULL (Production Activation)

## 1) Objectives
- Activate **SEO Autopilot in production** with **FULL (write-enabled) execution** while reusing existing components (analysis brain, planner/quality gate, safe-fix, GSC data, crawler, sitemap/robots/canonical).
- Add the **deferred execution layer** (currently missing) to:
  - publish **Landings** from existing `SEO_DRAFT_PROPOSAL` items after quality gate + duplicate protection;
  - generate **Articles** internally (Italian, IT target) with **max 1/day**, using existing `seo_autopilot/llm.py` (Emergent LLM) and existing content collections;
  - run **SEO safe-fix** for fixable issues and re-run quality gate before publish;
  - apply **internal linking** updates to prevent orphans;
  - process **existing drafts** and publish those that PASS.
- Keep non-SEO modules untouched (OF/X/Telegram/Instagram/public design).

## 2) Implementation Steps

### Phase 1 — Core POC (Isolation): prove “proposal → quality gate → safe-fix → publish landing”
**User stories**
1. As an admin, I want to execute ONE landing proposal end-to-end so I can verify publish safety before enabling automation.
2. As an admin, I want duplicate protection to block publishing if intent/slug already exists.
3. As an admin, I want a failed quality gate to keep content in draft with clear reasons.
4. As an admin, I want safe-fix to auto-correct missing/invalid SEO fields and retry quality gate.
5. As an admin, I want public mutations to be allowed only in FULL mode and tracked per run.

**POC steps**
- Implement `seo_autopilot/executor.py` (new) with:
  - `execute_one_proposal(proposal_id/slug, dry_run: bool)`
  - Uses existing `planner.py` checks + `v1_seo.py` validations where applicable.
  - Creates/updates a Landing in `landings_col` only after PASS.
  - Duplicate guard: slug uniqueness + “intent key” (cluster/query canonical) uniqueness.
- Modify `seo_autopilot/mode.py`:
  - Replace hard lock with `FULL_LOCKED = env flag` (default true) to enable controlled production activation.
- Update `seo_autopilot/engine.py` public mutation gate:
  - In FULL mode, allow `PUBLIC_MUTATIONS > 0` but require it to match expected mutations list recorded by executor.
- Add minimal admin route:
  - `POST /api/admin/seo-autopilot/execute/proposal/{slug}?dry_run=true|false`
- Write a minimal python script (or pytest) that:
  - runs dry-run, verifies no public changes;
  - runs execute, verifies landing published + appears in sitemap (if enabled).
- Fix until POC is deterministic and idempotent.

### Phase 2 — V1 App Development (Execution layer + automation)
**User stories**
1. As an admin, I want all existing drafts to be processed and auto-published if they pass quality gate.
2. As an admin, I want the system to publish at most 1 new article/day automatically.
3. As an admin, I want landings to be published automatically only when there is a distinct opportunity.
4. As an admin, I want internal linking applied so new pages are not orphaned.
5. As an admin, I want sitemap to auto-include only indexable published URLs.

**Build steps**
- Executor expansion:
  - `process_backlog()` to:
    - fetch all `SEO_DRAFT_PROPOSAL` and attempt publish pipeline;
    - scan existing CMS drafts (articles/landings/models/categories) and run quality+safe-fix+publish.
  - Add `article_generator.py` (new, internal):
    - uses `seo_autopilot/llm.py` with Italian prompts;
    - creates article doc in `articles_col` with SEO fields, internal links, `indicizzabile=true`;
    - respects `MAX_ARTICLES_PER_DAY=1` from settings.
  - Add `internal_linking_apply.py` (new):
    - use existing link graph logic in `v1_seo.py` (or reuse crawler render graph) to add/update `modelle_correlate` and internal link blocks.
  - Add `safe_fix_apply.py` (new):
    - call existing safe-fix routines in `v1_seo.py` or implement minimal safe fixes (title/meta/canonical/robots/indexable fields) using the same rules.
- Production flags/settings:
  - Add settings keys:
    - `seo_autopilot_enabled` (bool)
    - `seo_autopilot_mode` (OFF/READ_ONLY/FULL)
    - `seo_auto_publish_enabled` (bool)
    - `seo_max_articles_per_day` (int default 1)
    - `public_landing_routes` (ensure enabled for landings)
  - Wire these into `seo_autopilot/mode.py` and executor.
- Scheduler:
  - Add/enable jobs in `v1_jobs.py`:
    - daily `seo_ap_execute` (process drafts + generate article if under limit)
    - periodic `seo_ap_maintenance` (safe-fix + internal-linking refresh)
- API/control layer:
  - Extend `/api/admin/seo-autopilot/status` to expose production-ready booleans + next run times.

**Testing (end-to-end)**
- Update/add tests in `tests/test_seo_autopilot.py`:
  - FULL mode write guard works; READ_ONLY blocks writes.
  - Draft→Ready→Published transitions.
  - Duplicate protection.
  - Article generation caps at 1/day.
  - Sitemap includes published+indexable, excludes drafts/noindex.
  - Internal linking reduces orphans.

### Phase 3 — Production activation + backfill
**User stories**
1. As an admin, I want a safe activation procedure with a stop condition if any test fails.
2. As an admin, I want existing drafts auto-processed immediately after deploy.
3. As an admin, I want a report of how many drafts were published vs blocked.
4. As an admin, I want Search Console absence to not block publishing.
5. As an admin, I want the system to keep running after activation (not reverting to READ_ONLY).

**Steps**
- Workspace: run full test suite; confirm no non-SEO modules changed.
- Deploy to production.
- Production: set `SEO_AUTOPILOT_MODE=FULL` and enable settings (auto publish, generators).
- Run a single controlled execution:
  - execute proposals + process drafts; publish only PASS.
- Verify sitemap/robots/canonical/indexability via existing `/api/sitemap.xml` and audits.
- Leave scheduler enabled for future runs.

## 3) Next Actions
1. Implement Phase 1 POC (executor + mode unlock + single proposal execution route) and make it pass tests.
2. Implement Phase 2 automation (draft processing, article generator 1/day, internal linking apply, safe-fix apply, scheduler jobs) + comprehensive tests.
3. Prepare production activation checklist (env + settings + flags).
4. After user deploy confirmation, perform production backfill run and output final report.

## 4) Success Criteria
- `SEO_AUTOPILOT_ACTIVE=true` and `SEO_AUTOPILOT_PRODUCTION=true` (FULL mode write-enabled).
- `AUTO_PUBLISH_ENABLED=true`.
- `ARTICLE_GENERATOR_ACTIVE=true` with `MAX_ARTICLES_PER_DAY=1`.
- `LANDING_GENERATOR_ACTIVE=true` (publishes distinct proposals only).
- `INTERNAL_LINKING_ACTIVE=true` (orphans reduced/none for new pages).
- `SITEMAP_AUTO_UPDATE=true` (published+indexable only).
- `SEO_SAFE_FIX_ACTIVE=true` (auto-fix then re-check then publish).
- Existing drafts processed: valid drafts published, failed ones remain drafts with reasons.
- Tests: all required checks PASS; no changes to OF/X/Telegram/Instagram modules.
