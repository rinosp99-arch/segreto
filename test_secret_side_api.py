#!/usr/bin/env python3
"""
Quick test for secret-side API endpoint
Verifies that /api/models/{slug}/segreto returns 3 image + 2 video pairs
"""
import requests
import sys

BASE_URL = "https://secret-side.preview.emergentagent.com/api"

def test_secret_side_media_pairs():
    """Test that secret side returns correct media structure"""
    print("🔍 Testing secret-side API endpoint...")
    
    # First get a model slug
    try:
        resp = requests.get(f"{BASE_URL}/models?filtro=tutte", timeout=10)
        if resp.status_code != 200:
            print(f"❌ Failed to get models list: {resp.status_code}")
            return False
        
        models = resp.json().get("items", [])
        if not models:
            print("❌ No models found")
            return False
        
        # Test with first two models (francesca-rossi and vanessa-neri mentioned in requirements)
        test_slugs = []
        for model in models[:3]:
            slug = model.get("slug")
            if slug:
                test_slugs.append(slug)
        
        if not test_slugs:
            print("❌ No model slugs found")
            return False
        
        print(f"ℹ️  Testing with models: {test_slugs}")
        
        all_passed = True
        for slug in test_slugs:
            print(f"\n📋 Testing model: {slug}")
            resp = requests.get(f"{BASE_URL}/models/{slug}/segreto", timeout=10)
            
            if resp.status_code != 200:
                print(f"  ❌ Failed to get secret side: {resp.status_code}")
                all_passed = False
                continue
            
            data = resp.json()
            
            # Check required fields
            if "media_pairs" not in data:
                print(f"  ❌ Missing media_pairs field")
                all_passed = False
                continue
            
            if "tema" not in data:
                print(f"  ❌ Missing tema field")
                all_passed = False
                continue
            
            if "messaggio_35s" not in data:
                print(f"  ❌ Missing messaggio_35s field")
                all_passed = False
                continue
            
            # Check media pairs structure
            pairs = data["media_pairs"]
            if not isinstance(pairs, list):
                print(f"  ❌ media_pairs is not a list")
                all_passed = False
                continue
            
            # Count images and videos
            images = [p for p in pairs if p.get("tipo") == "image"]
            videos = [p for p in pairs if p.get("tipo") == "video"]
            
            print(f"  ℹ️  Found {len(images)} images, {len(videos)} videos (total: {len(pairs)} pairs)")
            
            # Verify each pair has pubblico and segreto
            for i, pair in enumerate(pairs):
                if "pubblico" not in pair:
                    print(f"  ⚠️  Pair {i} missing 'pubblico'")
                if "segreto" not in pair:
                    print(f"  ⚠️  Pair {i} missing 'segreto'")
                if pair.get("pubblico") and not pair["pubblico"].get("url"):
                    print(f"  ⚠️  Pair {i} pubblico missing URL")
                if pair.get("segreto") and not pair["segreto"].get("url"):
                    print(f"  ⚠️  Pair {i} segreto missing URL")
            
            # Check if we have at least 3 images and 2 videos
            if len(images) >= 3 and len(videos) >= 2:
                print(f"  ✅ PASSED - Has {len(images)} images (≥3) and {len(videos)} videos (≥2)")
            else:
                print(f"  ❌ FAILED - Expected ≥3 images and ≥2 videos, got {len(images)} images and {len(videos)} videos")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_secret_side_media_pairs()
    print("\n" + "="*60)
    if success:
        print("✅ Secret-side API test PASSED")
        sys.exit(0)
    else:
        print("❌ Secret-side API test FAILED")
        sys.exit(1)
