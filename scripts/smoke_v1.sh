#!/bin/bash
# Smoke test SUPER API v1 (local)
B=localhost:8001
TOKEN=$(curl -s -X POST $B/api/admin/login -H 'Content-Type: application/json' -d '{"email":"admin@latosegreto.it","password":"LatoSegreto2025!"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
H="Authorization: Bearer $TOKEN"
J="Content-Type: application/json"
step() { echo; echo "=== $1"; }

step "auth/me"; curl -s $B/api/v1/auth/me -H "$H"
step "create API key AI_OPERATOR"
KEY=$(curl -s -X POST $B/api/v1/auth/keys -H "$H" -H "$J" -d '{"name":"chatgpt-test","role":"AI_OPERATOR"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['api_key'])")
echo "key prefix ${KEY:0:8}"
K="X-API-Key: $KEY"
step "AI status via API key"; curl -s $B/api/v1/ai/status -H "$K" | python -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['summary'])"
step "AI: key cannot manage keys (403 expected)"; curl -s -o /dev/null -w "%{http_code}\n" $B/api/v1/auth/keys -H "$K"
step "AI create Vanessa Test"
curl -s -X POST $B/api/v1/ai/models/create -H "$K" -H "$J" -d '{"nome":"Vanessa Test","frase":"Prova.","categorie":["more"]}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary']); print(d['next_steps']); print(d['data']['slug'])"
step "AI update bio + onlyfans (idempotent)"
for i in 1 2; do curl -s -X POST $B/api/v1/ai/models/update -H "$K" -H "$J" -H "Idempotency-Key: upd-1" -D - -o /tmp/r.json -d '{"model":"vanessa test","changes":{"bio":"Bio pubblica di prova abbastanza lunga per la SEO e per il test.","bio_segreta":"Bio segreta.","onlyfans_url":"https://onlyfans.com/vanessatest","conferma_maggiorenne":true}}' | grep -i "idempotent\|x-request-id"; python -c "import json; d=json.load(open('/tmp/r.json')); print(d['summary'])"; done
step "AI media upload from URL (local media served by frontend) -> pair pubblico"
curl -s -X POST $B/api/v1/ai/media/upload -H "$K" -H "$J" -d '{"model":"vanessa-test","slot":"foto_card","side":"pubblico","url":"https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=600&q=80"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['summary']); print(d['data'].get('web_url'), d['data'].get('poster_url'))"
step "AI validate"; curl -s -X POST $B/api/v1/ai/models/validate -H "$K" -H "$J" -d '{"model":"Vanessa Test"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "AI publish (expected fail: missing media)"; curl -s -X POST $B/api/v1/ai/models/publish -H "$K" -H "$J" -d '{"model":"vanessa-test"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['summary'])"
step "v1 duplicate existing published model"
curl -s -X POST $B/api/v1/models/francesca-rossi/duplicate -H "$H" -H "$J" -d '{}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['slug'], d['workflow_status'])"
step "v1 publish duplicate (should be READY -> PUBLISHED)"
curl -s -X POST $B/api/v1/models/francesca-rossi-copia/publish -H "$H" -H "$J" -d '{}' | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('workflow_status'), d.get('detail'))"
step "v1 feature in home"; curl -s -X POST $B/api/v1/ai/models/feature -H "$K" -H "$J" -d '{"model":"francesca-rossi-copia","position":0,"badge":"NUOVA"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "public list first slug"; curl -s "$B/api/models?limit=2" | python -c "import sys,json; d=json.load(sys.stdin); print([i['slug'] for i in d['items']], d['total'])"
step "v1 archive + restore"; curl -s -X POST $B/api/v1/models/francesca-rossi-copia/archive -H "$H" -H "$J" -d '{}' | python -c "import sys,json; print(json.load(sys.stdin)['workflow_status'])"; curl -s "$B/api/models?limit=100" | python -c "import sys,json; d=json.load(sys.stdin); print('public total', d['total'])"; curl -s -X POST $B/api/v1/models/francesca-rossi-copia/restore -H "$H" -H "$J" -d '{}' | python -c "import sys,json; print(json.load(sys.stdin)['workflow_status'])"
step "versions + rollback of last update"
VID=$(curl -s "$B/api/v1/versions?entity=model&limit=1" -H "$H" | python -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
curl -s -X POST $B/api/v1/versions/$VID/rollback -H "$H" -H "$J" -d '{"reason":"test"}' | python -c "import sys,json; print(json.load(sys.stdin))"
step "SEO audit"; curl -s -X POST $B/api/v1/ai/seo/audit -H "$K" -H "$J" -d '{}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "SEO dry-run"; curl -s -X POST $B/api/v1/ai/seo/apply-safe-fixes -H "$K" -H "$J" -d '{"dry_run":true}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "SEO apply"; curl -s -X POST $B/api/v1/ai/seo/apply-safe-fixes -H "$K" -H "$J" -d '{}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "SEO issues open"; curl -s "$B/api/v1/seo/issues" -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(d['open_counts'])"
step "track v1 (IT lang) + legacy track"; curl -s -X POST $B/api/v1/track -H "$J" -H "Accept-Language: it-IT" -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari" -d '{"event":"model_view","model_slug":"francesca-rossi","session_id":"s-test-1"}'; curl -s -X POST $B/api/track -H "$J" -H "CF-IPCountry: IT" -d '{"tipo":"of_click","model_slug":"francesca-rossi","session_id":"s-test-1","cta_source":"of_click_gallery"}'; echo
step "analytics italy"; curl -s "$B/api/v1/analytics/italy?range=1g" -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(d['model_views_italy'], d['italian_share'], d['devices'])"
step "AI query best converting"; curl -s -X POST $B/api/v1/ai/analytics/query -H "$K" -H "$J" -d '{"question":"quale modella converte meglio?","range":"1g"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "AI daily summary"; curl -s $B/api/v1/ai/daily-summary -H "$K" | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'][:300])"
step "landing create"; curl -s -X POST $B/api/v1/ai/landing/create -H "$K" -H "$J" -d '{"titolo":"Landing Test","headline":"Il lato che non conosci","model_slugs":["francesca-rossi"],"cta":{"testo":"ENTRA"},"publish":true}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['summary'])"
step "public landing"; curl -s $B/api/landings/landing-test | python -c "import sys,json; d=json.load(sys.stdin); print(d['slug'], len(d['model_cards']))"
step "experiment"; EXP=$(curl -s -X POST $B/api/v1/experiments -H "$H" -H "$J" -d '{"nome":"CTA test","target_type":"cta","variants":[{"nome":"A","value":"CONTINUA CON ME"},{"nome":"B","value":"VIENI A VEDERE"}]}' | python -c "import sys,json; print(json.load(sys.stdin)['id'])"); curl -s -X POST $B/api/v1/experiments/$EXP/start -H "$H" | python -c "import sys,json; print(json.load(sys.stdin)['stato'])"; curl -s "$B/api/experiments/assign?session_id=abc"; echo; curl -s -X POST $B/api/v1/experiments/$EXP/conclude -H "$H" -H "$J" -d '{"winner_variant_id":"x"}' | python -c "import sys,json; print(json.load(sys.stdin)['detail']['message'][:80])"
step "health run"; curl -s -X POST $B/api/v1/health/run -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(d['overall'], [(c['name'],c['status']) for c in d['checks']], d['actions'])"
step "jobs"; curl -s $B/api/v1/jobs -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(d['scheduler_running'], [j['name'] for j in d['items']])"
step "run job seo_scan"; curl -s -X POST $B/api/v1/jobs/seo_scan/run -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['duration_ms'])"
step "backup"; curl -s -X POST $B/api/v1/backup -H "$H" -H "$J" -d '{}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'][:8], d['size'], d['counts'].get('models'))"
step "config flags"; curl -s $B/api/v1/config/flags -H "$H" | python -c "import sys,json; print(json.load(sys.stdin)['flags'])"
step "webhook create"; curl -s -X POST $B/api/v1/webhooks -H "$H" -H "$J" -d '{"url":"https://example.com/hook","events":["model.published"]}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'][:8], d['secret'][:10])"
step "dashboard"; curl -s "$B/api/v1/dashboard/overview" -H "$H" | python -c "import sys,json; d=json.load(sys.stdin); print(list(d.keys())); print(d['api_status']['health'], d['seo_health'])"
step "rate limit check (429 expected after burst?) skip"
step "read-only user cannot write legacy admin"
curl -s -X POST $B/api/v1/auth/users -H "$H" -H "$J" -d '{"email":"ro@test.it","password":"password123","role":"READ_ONLY"}' >/dev/null
RT=$(curl -s -X POST $B/api/admin/login -H "$J" -d '{"email":"ro@test.it","password":"password123"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w "legacy PUT settings as READ_ONLY -> %{http_code}\n" -X PUT $B/api/admin/settings -H "Authorization: Bearer $RT" -H "$J" -d '{}'
curl -s -o /dev/null -w "v1 models GET as READ_ONLY -> %{http_code}\n" $B/api/v1/models -H "Authorization: Bearer $RT"
curl -s -o /dev/null -w "v1 models POST as READ_ONLY -> %{http_code}\n" -X POST $B/api/v1/models -H "Authorization: Bearer $RT" -H "$J" -d '{"nome":"x"}'
step "cleanup"; curl -s -X DELETE $B/api/v1/models/vanessa-test -H "$H" | python -c "import sys,json; print(json.load(sys.stdin)['soft_deleted'])"; curl -s -X DELETE $B/api/v1/models/francesca-rossi-copia -H "$H" >/dev/null; curl -s -X DELETE $B/api/v1/landings/landing-test -H "$H" >/dev/null
curl -s "$B/api/models?limit=100" | python -c "import sys,json; d=json.load(sys.stdin); print('public total after cleanup', d['total'])"
