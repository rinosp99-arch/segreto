"""SEO AUTOPILOT / ORGANIC GROWTH ENGINE — the READ_ONLY "brain".

Analyses Search Console data, the model database and the public site (crawl + render + Google inspection) to build a keyword
universe, clusters, intents, opportunities, a keyword->page map, landing DRAFT proposals (never public), cannibalization and
technical reports, a backlog and a full decision log. It NEVER touches the public site: every write action is guarded by
`mode.py` and fails unless SEO_AUTOPILOT_MODE == FULL, which is locked in this phase.
"""
