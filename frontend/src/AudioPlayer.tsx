import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { animate, stagger } from "animejs";
import { FileIcon, Icon, reduced } from "./ui";

export interface Tags { title?: string; artist?: string; album?: string; year?: string; track?: string; genre?: string; cover?: string }

const BARS = 56;
const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
const clock = (s: number) => (isFinite(s) && s > 0 ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00");
const rest = (i: number) => 0.16 + 0.1 * Math.sin(i * 0.55) + 0.06 * Math.sin(i * 1.7);          // the bars' height when nothing plays

/** A player for audio: cover art or the file icon, title and artist from the file's tags, bars that follow the sound (Web
 *  Audio) or breathe on their own (anime.js) when that is not possible, a seek bar, play, jump, speed and volume. With
 *  reduced motion the bars stay still. */
export function AudioPlayer({ src, name, tags, onError }: { src: string; name: string; tags?: Tags; onError: () => void }) {
  const au = useRef<HTMLAudioElement>(null); const eq = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false); const [t, setT] = useState(0); const [dur, setDur] = useState(0);
  const [vol, setVol] = useState(1); const [speed, setSpeed] = useState(1);
  const ctx = useRef<AudioContext | null>(null); const an = useRef<AnalyserNode | null>(null); const raf = useRef(0);
  const sim = useRef<ReturnType<typeof animate> | null>(null); const lvl = useRef(new Float32Array(BARS).fill(0)); const calm = useReducedMotion();
  const bars = () => Array.from(eq.current?.children ?? []) as HTMLElement[];
  const settle = () => bars().forEach((b, i) => { b.style.transform = `scaleY(${rest(i)})`; });

  const stop = () => { cancelAnimationFrame(raf.current); sim.current?.pause(); sim.current = null; eq.current?.classList.remove("live"); settle(); };
  const start = () => {
    if (calm || reduced()) return;
    const el = au.current; if (!el) return;
    try {
      if (!ctx.current) {
        const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        ctx.current = new AC();
        const node = ctx.current.createMediaElementSource(el);
        an.current = ctx.current.createAnalyser(); an.current.fftSize = 256; an.current.smoothingTimeConstant = 0.78;
        node.connect(an.current); an.current.connect(ctx.current.destination);
      }
      void ctx.current.resume();
      const data = new Uint8Array(an.current!.frequencyBinCount), els = bars();
      eq.current?.classList.add("live");                                          // no CSS transition while a frame loop is writing the heights
      lvl.current.set(els.map((_, i) => rest(i)));
      const tick = (now: number) => {
        an.current!.getByteFrequencyData(data);
        els.forEach((b, i) => {
          const bin = 2 + Math.floor((i / els.length) * (data.length * 0.62));
          const v = data[bin] / 255, idle = rest(i) + 0.05 * Math.sin(now / 420 + i * 0.6);       // a quiet passage still breathes a little
          const want = Math.max(idle, 0.08 + v * 0.92), cur = lvl.current[i];
          const next = cur + (want - cur) * (want > cur ? 0.55 : 0.16);                            // quick to rise, slow to fall: smooth, not jittery
          lvl.current[i] = next;
          b.style.transform = `scaleY(${next.toFixed(3)})`;
        });
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
    } catch {                                                                    // no Web Audio: let the bars move on their own
      sim.current = animate(bars(), { scaleY: () => 0.2 + Math.random() * 0.8, duration: 420, ease: "inOutSine", loop: true, alternate: true, delay: stagger(22) });
    }
  };

  useEffect(() => { settle(); return () => { stop(); void ctx.current?.close(); ctx.current = null; au.current?.pause(); }; }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (au.current) au.current.volume = vol; }, [vol]);
  useEffect(() => { if (au.current) au.current.playbackRate = speed; }, [speed]);

  const toggle = () => { const a = au.current; if (!a) return; if (a.paused) void a.play().catch(onError); else a.pause(); };
  const jump = (s: number) => { const a = au.current; if (a) a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + s)); };
  const pct = dur ? (t / dur) * 100 : 0;
  const spring = calm ? { duration: 0 } : { type: "spring" as const, stiffness: 420, damping: 30 };

  return (
    <div className="ap" onKeyDown={e => { if (e.code === "Space" && !(e.target as HTMLElement).closest("button, input")) { e.preventDefault(); toggle(); } }}>
      <motion.div className="ap-art" initial={calm ? false : { opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} transition={spring}>
        {tags?.cover ? <img src={tags.cover} alt="Cover art" /> : <FileIcon name={name} />}
      </motion.div>
      <div className="ap-main">
        <div className="ap-meta">
          <b className="ap-title">{tags?.title || name}</b>
          {tags?.artist && <span className="ap-artist">{tags.artist}</span>}
          {(tags?.album || tags?.year) && <span className="sub">{[tags.album, tags.year].filter(Boolean).join(", ")}</span>}
        </div>
        <div className="ap-eq" ref={eq} aria-hidden="true">{Array.from({ length: BARS }, (_, i) => <i key={i} style={{ transform: `scaleY(${rest(i)})` }} />)}</div>
        <div className="ap-seek">
          <span className="ap-time">{clock(t)}</span>
          <input type="range" min={0} max={dur || 0} step={0.1} value={Math.min(t, dur || 0)} aria-label="Position" aria-valuetext={`${clock(t)} of ${clock(dur)}`}
            style={{ "--p": pct + "%" } as React.CSSProperties} onChange={e => { const a = au.current; if (a) a.currentTime = +e.target.value; setT(+e.target.value); }} />
          <span className="ap-time">{clock(dur)}</span>
        </div>
        <div className="ap-ctl">
          <button type="button" className="quiet" onClick={() => jump(-10)} aria-label="Back 10 seconds" title="Back 10 seconds">-10 s</button>
          <motion.button type="button" className="primary ap-play" onClick={toggle} aria-label={playing ? "Pause" : "Play"} whileTap={calm ? undefined : { scale: 0.93 }} transition={spring}>
            <Icon name={playing ? "pause" : "play"} />
          </motion.button>
          <button type="button" className="quiet" onClick={() => jump(10)} aria-label="Forward 10 seconds" title="Forward 10 seconds">+10 s</button>
          <span className="grow" />
          <button type="button" className="quiet" onClick={() => setSpeed(s => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length])} aria-label={`Speed ${speed} times, click to change`} title="Playback speed">{speed}x</button>
          <label className="ap-vol"><Icon name="volume" /><input type="range" min={0} max={1} step={0.05} value={vol} aria-label="Volume" style={{ "--p": vol * 100 + "%" } as React.CSSProperties} onChange={e => setVol(+e.target.value)} /></label>
        </div>
      </div>
      <audio ref={au} src={src} preload="metadata" onError={onError} onLoadedMetadata={e => setDur(e.currentTarget.duration)} onDurationChange={e => setDur(e.currentTarget.duration)}
        onTimeUpdate={e => setT(e.currentTarget.currentTime)} onVolumeChange={e => setVol(e.currentTarget.muted ? 0 : e.currentTarget.volume)} onRateChange={e => setSpeed(e.currentTarget.playbackRate)} onPlay={() => { setPlaying(true); start(); }} onPause={() => { setPlaying(false); stop(); }} onEnded={() => { setPlaying(false); stop(); }} />
    </div>
  );
}
