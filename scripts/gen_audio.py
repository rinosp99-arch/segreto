#!/usr/bin/env python3
"""Generate warm, sensual cinematic audio for the Secret Side.
Outputs iOS/Safari-friendly MP3 files into /app/frontend/public/audio/:
  - activation.mp3  : soft ~1.2s activation swell (no click/impact)
  - amb_<preset>.mp3 : ~16s seamless ambient loops (sensuale/notturno/lusso/intimo/intenso)
All synthesized (no external assets). Small, mono, ~72kbps.
"""
import os, subprocess, numpy as np

SR = 32000
OUT = "/app/frontend/public/audio"
TMP = "/tmp/audiogen"
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

def soft_clip(x):
    return np.tanh(x * 1.1) * 0.92

def norm(x, peak=0.9):
    m = np.max(np.abs(x)) + 1e-9
    return x / m * peak

def onepole_lp(x, cutoff):
    # simple one-pole lowpass for warmth
    a = np.exp(-2*np.pi*cutoff/SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1-a)*x[i] + a*acc
        y[i] = acc
    return y

def reverb(x, mix=0.22):
    # tiny multi-tap feedback for space/warmth
    out = x.copy()
    for delay_ms, g in [(53, 0.30), (97, 0.24), (151, 0.18), (211, 0.12)]:
        d = int(SR*delay_ms/1000)
        echo = np.zeros_like(x)
        echo[d:] = x[:-d]
        out += echo * g * mix
    return out

NOTE = lambda semi: 440.0 * (2 ** (semi/12.0))  # semitones from A4

def pad(dur, freqs, detune=0.004, vib=4.5, amp=0.5):
    n = int(SR*dur); t = np.arange(n)/SR
    y = np.zeros(n)
    for f in freqs:
        v = 1 + 0.003*np.sin(2*np.pi*vib*t + f)   # subtle vibrato
        for k,(mul,g) in enumerate([(1,1.0),(2,0.28),(3,0.12)]):  # few partials = warm
            det = 1 + detune*((k%2)*2-1)
            y += g*np.sin(2*np.pi*f*mul*det*t*v)
    y = onepole_lp(y, 1600)
    return y*amp

def env_loop(n, attack, release):
    e = np.ones(n)
    a = int(SR*attack); r = int(SR*release)
    if a>0: e[:a] = np.linspace(0,1,a)
    if r>0: e[-r:] = np.linspace(1,0,r)
    return e

def kick(dur=0.28, f0=110, f1=45, amp=0.9):
    n=int(SR*dur); t=np.arange(n)/SR
    f = f1 + (f0-f1)*np.exp(-t*22)
    ph = 2*np.pi*np.cumsum(f)/SR
    e = np.exp(-t*7)
    return np.sin(ph)*e*amp

def hat(dur=0.05, amp=0.12):
    n=int(SR*dur); t=np.arange(n)/SR
    noise = np.random.randn(n)
    # highpass-ish by differencing
    noise = np.diff(np.concatenate([[0],noise]))
    e = np.exp(-t*60)
    return noise*e*amp

def place(track, sample, pos):
    i=int(pos*SR); j=min(len(track), i+len(sample))
    track[i:j]+=sample[:j-i]

def build_ambient(bpm, chord_semis, bars=8, kick_amp=0.7, hat_amp=0.1, pad_amp=0.5,
                  sub_amp=0.5, rev=0.22, brightness=1600):
    beat = 60.0/bpm
    loop = beat*4*bars
    n=int(SR*loop)
    freqs=[NOTE(s) for s in chord_semis]
    # pad (chord) with slow swell, looped seamlessly (use full-length steady pad)
    p = np.zeros(n); t=np.arange(n)/SR
    for f in freqs:
        v=1+0.0025*np.sin(2*np.pi*0.12*t)
        p+=np.sin(2*np.pi*f*t*v)+0.26*np.sin(2*np.pi*2*f*t)+0.10*np.sin(2*np.pi*3*f*t)
    p=onepole_lp(p,brightness)
    # slow amplitude LFO (period divides loop)
    lfo=0.82+0.18*np.sin(2*np.pi*(1.0/(loop))*t*2)
    p=p*lfo*pad_amp/len(freqs)
    # sub bass on root, gentle pulse per beat (soft sidechain feel)
    root=NOTE(chord_semis[0]-12)
    sub=np.sin(2*np.pi*root*t)
    duck=np.ones(n)
    for b in range(int(bars*4)):
        pos=b*beat
        i=int(pos*SR)
        seg=int(SR*min(beat,0.35))
        duck[i:i+seg]*=np.linspace(0.55,1.0,seg)
    sub=sub*duck*sub_amp
    # drums
    drums=np.zeros(n)
    for b in range(int(bars*4)):
        pos=b*beat
        place(drums, kick(amp=kick_amp), pos)
        # soft offbeat hat
        place(drums, hat(amp=hat_amp), pos+beat*0.5)
    mix = p + sub + drums
    mix = reverb(mix, rev)
    mix = soft_clip(mix)
    # gentle overall fade at loop seam to guarantee zero-cross seamlessness
    x = norm(mix, 0.82)
    return x

PRESETS = {
    # sensual R&B, warm minor9
    "sensuale": dict(bpm=74, chord_semis=[3,7,10,14], kick_amp=0.65, hat_amp=0.10, pad_amp=0.55, sub_amp=0.5, rev=0.24, brightness=1500),
    # darker, mysterious, sparse
    "notturno": dict(bpm=68, chord_semis=[-2,5,8,12], kick_amp=0.55, hat_amp=0.06, pad_amp=0.5, sub_amp=0.6, rev=0.30, brightness=1100),
    # lush lounge major9, silky
    "lusso":    dict(bpm=80, chord_semis=[0,4,7,11], kick_amp=0.6, hat_amp=0.12, pad_amp=0.6, sub_amp=0.45, rev=0.26, brightness=1900),
    # intimate minimal, very soft, almost no beat
    "intimo":   dict(bpm=70, chord_semis=[2,5,9,12], kick_amp=0.32, hat_amp=0.04, pad_amp=0.6, sub_amp=0.4, rev=0.28, brightness=1300),
    # more rhythmic but elegant
    "intenso":  dict(bpm=84, chord_semis=[3,6,10,13], kick_amp=0.8, hat_amp=0.16, pad_amp=0.5, sub_amp=0.55, rev=0.20, brightness=1700),
}

def build_activation():
    dur=1.25; n=int(SR*dur); t=np.arange(n)/SR
    # warm chord bloom (root + fifth + tenth)
    freqs=[NOTE(-9), NOTE(-2), NOTE(3), NOTE(7)]  # soft, low-ish
    bloom=np.zeros(n)
    for f in freqs:
        bloom+=np.sin(2*np.pi*f*t)+0.22*np.sin(2*np.pi*2*f*t)
    bloom=onepole_lp(bloom,1400)
    e_bloom=np.clip((t/0.5),0,1)*np.exp(-np.clip(t-0.5,0,None)*2.2)  # swell then soft decay
    bloom=bloom*e_bloom*0.5/len(freqs)
    # airy rising whoosh (filtered noise sweep, breathy)
    noise=np.random.randn(n)
    # rising lowpass by mixing progressively brighter one-pole passes
    lp1=onepole_lp(noise,500); lp2=onepole_lp(noise,2500)
    sweep=(1-t/dur)[:,]  # 0..1
    air=lp1*(1-t/dur)+lp2*(t/dur)
    e_air=np.clip(t/0.25,0,1)*np.exp(-np.clip(t-0.35,0,None)*3.5)
    air=air*e_air*0.10
    # sub swell underlay
    sub=np.sin(2*np.pi*NOTE(-21)*t)*np.clip(t/0.4,0,1)*np.exp(-np.clip(t-0.5,0,None)*2.0)*0.35
    mix=reverb(bloom+air+sub, 0.25)
    mix=soft_clip(mix)
    # ensure soft tail to zero
    tail=int(SR*0.15); mix[-tail:]*=np.linspace(1,0,tail)
    return norm(mix,0.85)

def write_mp3(x, path):
    x16=(np.clip(x,-1,1)*32767).astype('<i2')
    raw=os.path.join(TMP,"tmp.raw"); x16.tofile(raw)
    subprocess.run(["ffmpeg","-y","-f","s16le","-ar",str(SR),"-ac","1","-i",raw,
                    "-codec:a","libmp3lame","-b:a","72k",path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__=="__main__":
    np.random.seed(7)
    write_mp3(build_activation(), os.path.join(OUT,"activation.mp3"))
    print("activation.mp3 done")
    for name,cfg in PRESETS.items():
        x=build_ambient(**cfg)
        write_mp3(x, os.path.join(OUT,f"amb_{name}.mp3"))
        print(f"amb_{name}.mp3 done")
    for f in sorted(os.listdir(OUT)):
        p=os.path.join(OUT,f); print(f, os.path.getsize(p)//1024, "KB")
