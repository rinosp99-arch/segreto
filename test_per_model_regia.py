#!/usr/bin/env python3
"""
Test per-model regia differentiation for LATO SEGRETO
Verifies that francesca-rossi, vanessa-neri, and federica-sole have different regia values
"""
import requests
import json

BASE_URL = "https://secret-side.preview.emergentagent.com/api"

models = ["francesca-rossi", "vanessa-neri", "federica-sole"]

print("=" * 80)
print("PER-MODEL REGIA DIFFERENTIATION TEST")
print("=" * 80)

regia_data = {}

for model_slug in models:
    print(f"\n🔍 Testing {model_slug}...")
    try:
        response = requests.get(f"{BASE_URL}/models/{model_slug}/segreto", timeout=10)
        if response.status_code == 200:
            data = response.json()
            regia = data.get("regia", {})
            cta_temp = data.get("cta_temporizzata", {})
            social = data.get("social", {})
            
            print(f"✅ SUCCESS - Got secret side data")
            print(f"   Regia preset: {regia.get('preset')}")
            print(f"   Fumo: {regia.get('fumo')}")
            print(f"   Luci: {regia.get('luci')}")
            print(f"   Glow: {regia.get('glow')}")
            print(f"   Movimento: {regia.get('movimento')}")
            print(f"   Ambiente sonoro attivo: {regia.get('ambiente_sonoro', {}).get('attivo')}")
            print(f"   Ambiente sonoro volume: {regia.get('ambiente_sonoro', {}).get('volume')}")
            print(f"   CTA temporizzata attivo: {cta_temp.get('attivo')}")
            print(f"   CTA temporizzata ritardo: {cta_temp.get('ritardo')}s")
            print(f"   Social links: {list(social.keys())}")
            
            # Calculate intensity for ambience opacity
            fumo = regia.get('fumo', 35)
            luci = regia.get('luci', 55)
            glow = regia.get('glow', 40)
            intensity = ((fumo + luci + glow) / 3) / 100
            ambience_opacity = 0.3 + intensity * 0.7
            print(f"   Calculated ambience opacity: {ambience_opacity:.3f}")
            
            regia_data[model_slug] = {
                "regia": regia,
                "cta_temporizzata": cta_temp,
                "social": social,
                "ambience_opacity": ambience_opacity
            }
        else:
            print(f"❌ FAILED - Status: {response.status_code}")
    except Exception as e:
        print(f"❌ ERROR - {str(e)}")

print("\n" + "=" * 80)
print("DIFFERENTIATION ANALYSIS")
print("=" * 80)

# Check if all models have different regia values
if len(regia_data) == 3:
    print("\n✅ All 3 models returned secret side data")
    
    # Compare regia values
    print("\n📊 Regia comparison:")
    for model in models:
        r = regia_data[model]["regia"]
        print(f"  {model}:")
        print(f"    Preset: {r.get('preset')}, Fumo: {r.get('fumo')}, Luci: {r.get('luci')}, Glow: {r.get('glow')}, Movimento: {r.get('movimento')}")
        print(f"    Ambience opacity: {regia_data[model]['ambience_opacity']:.3f}")
    
    # Check if values are different
    presets = [regia_data[m]["regia"].get("preset") for m in models]
    fumo_values = [regia_data[m]["regia"].get("fumo") for m in models]
    ambience_opacities = [regia_data[m]["ambience_opacity"] for m in models]
    
    if len(set(presets)) > 1:
        print("\n✅ Models have DIFFERENT presets")
    else:
        print("\n⚠️  WARNING: All models have the SAME preset")
    
    if len(set(fumo_values)) > 1:
        print("✅ Models have DIFFERENT fumo values")
    else:
        print("⚠️  WARNING: All models have the SAME fumo value")
    
    if len(set(ambience_opacities)) > 1:
        print("✅ Models have DIFFERENT ambience opacity (visual differentiation)")
    else:
        print("⚠️  WARNING: All models have the SAME ambience opacity")
    
    # Check social links
    print("\n📱 Social links comparison:")
    for model in models:
        social = regia_data[model]["social"]
        populated = [k for k, v in social.items() if v and k != "custom"]
        print(f"  {model}: {len(populated)} populated links - {populated}")
    
    # Check CTA temporizzata
    print("\n⏱️  CTA temporizzata comparison:")
    for model in models:
        cta = regia_data[model]["cta_temporizzata"]
        print(f"  {model}: attivo={cta.get('attivo')}, ritardo={cta.get('ritardo')}s")
    
    print("\n✅ PER-MODEL DIFFERENTIATION TEST COMPLETE")
else:
    print(f"\n❌ FAILED - Only {len(regia_data)}/3 models returned data")

print("=" * 80)
