import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { api, fmt, label, PreviewInfo } from "./api";
import { FileIcon, Icon, useRise } from "./ui";
import { AudioPlayer } from "./AudioPlayer";
import { DocView } from "./DocView";
import { closePreview, goPreview, openPreview, stepPreview, usePreviewState } from "./previewStore";
import { cached, clearInfoCache, loadInfo, patchCached, prefetch } from "./previewCache";
import { Kbd } from "./Shortcuts";
import { onControl, typingIn } from "./keys";

/** The eye button at the end of a file row. `ids` is every file in the list, so the arrow keys can step through them. */
export function PreviewButton({ id, ids, name }: { id: string; ids: string[]; name: string }) {
  return <button type="button" className="quiet pv-btn" title="Preview" aria-label={"Preview " + name} onClick={() => openPreview(ids, id)}><Icon name="eye" /></button>;
}

const when = (t: number) => new Date(t * 1000).toLocaleString();

function Table({ sheets, id }: { sheets: NonNullable<PreviewInfo["sheets"]>; id: string }) {
  const [k, setK] = useState(0); const calm = useReducedMotion();
  useEffect(() => setK(0), [id]);
  const s = sheets[Math.min(k, sheets.length - 1)];
  const rise = useRise("tbody tr", [id, k], { max: 36, step: 14, lift: 8 });
  if (!s) return <p className="sub pv-pad">This file has no sheets to show.</p>;
  const cols = Math.max(0, ...s.rows.map(r => r.length));
  return (
    <div className="pv-sheet">
      {sheets.length > 1 && <div className="pv-tabs" role="tablist">{sheets.map((x, i) => <button key={i} role="tab" aria-selected={i === k} className={i === k ? "on" : ""} onClick={() => setK(i)}>{x.name || `Sheet ${i + 1}`}{i === k && <motion.span layoutId="pv-tab-ink" className="pv-tab-ink" transition={calm ? { duration: 0 } : { type: "spring", stiffness: 640, damping: 42 }} />}</button>)}</div>}
      <div className="pv-scroll" ref={rise}>
        <table className="pv-table">
          <tbody>{s.rows.map((r, i) => <tr key={i}><th scope="row">{i + 1}</th>{Array.from({ length: cols }, (_, c) => <td key={c} title={r[c]}>{r[c] ?? ""}</td>)}</tr>)}</tbody>
        </table>
        {!s.rows.length && <p className="sub pv-pad">{s.name || "This sheet"} is empty.</p>}
        {s.truncated && <p className="sub pv-pad">Only the first rows are shown.</p>}
      </div>
    </div>
  );
}

function Pages({ d }: { d: PreviewInfo }) {
  const rise = useRise(".pv-page", [d.id], { max: 12, step: 70, lift: 16 });
  return (
    <div className="pv-scroll pv-pages" ref={rise}>
      {d.approximate && <p className="sub pv-note-top">An old Office file: this is the readable text found inside, not the page layout.</p>}
      {(d.pages ?? []).map((p, i) => (
        <section key={i} className="pv-page">
          {p.title && <h3>{p.title}</h3>}
          {p.lines.map((l, j) => <p key={j}>{l}</p>)}
          {!p.lines.length && <p className="sub">No text found.</p>}
        </section>
      ))}
      {d.truncated && <p className="sub pv-note-top">Only the first part is shown.</p>}
    </div>
  );
}

function Archive({ d }: { d: PreviewInfo }) {
  const rise = useRise("tbody tr", [d.id], { max: 30, step: 12, lift: 8 });
  return (
    <div className="pv-scroll" ref={rise}>
      <p className="sub pv-pad">{(d.total ?? 0).toLocaleString()} items inside. Nothing is unpacked.</p>
      <table className="pv-table"><tbody>{(d.entries ?? []).map((e, i) => <tr key={i}><td title={e.name}>{e.name}</td><td className="num">{fmt(e.size)}</td></tr>)}</tbody></table>
      {d.truncated && <p className="sub pv-pad">Only the first {(d.entries ?? []).length} files are listed.</p>}
    </div>
  );
}

/** A picture that fades in when it has loaded (and at once when it was already in the cache) instead of popping into place. */
function FadeImg({ src, alt, onError, zoom = 1, rot = 0 }: { src: string; alt: string; onError: () => void; zoom?: number; rot?: number }) {
  const [ready, setReady] = useState(false);
  const ref = (el: HTMLImageElement | null) => { if (el?.complete && el.naturalWidth) setReady(true); };
  const style: React.CSSProperties = {};
  if (zoom > 1) { style.width = zoom * 100 + "%"; style.maxWidth = "none"; style.maxHeight = "none"; }
  if (rot) style.transform = `rotate(${rot}deg)`;
  return <img ref={ref} className={"pv-fade" + (ready ? " ready" : "")} src={src} alt={alt} decoding="async" style={style} onLoad={() => setReady(true)} onError={onError} />;
}

function Body({ d, zoom, rot }: { d: PreviewInfo; zoom: number; rot: number }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [d.id]);
  if (d.mode === "none") return <div className="pv-center"><FileIcon name={d.name} /><p>{d.reason}</p></div>;
  if (broken) return <div className="pv-center"><FileIcon name={d.name} /><p>The browser cannot show this {d.mode === "audio" || d.mode === "video" ? "format" : "file"} directly. It is still backed up and can be restored.</p></div>;
  if (d.mode === "image") return <div className={"pv-center pv-media" + (zoom > 1 ? " zoomed" : "")}><FadeImg key={d.id} src={d.raw!} alt={d.name} zoom={zoom} rot={rot} onError={() => setBroken(true)} /></div>;
  if (d.mode === "video") return <div className="pv-center pv-media"><video src={d.raw} controls preload="metadata" onError={() => setBroken(true)} /></div>;
  if (d.mode === "audio") return <div className="pv-center pv-audio"><AudioPlayer key={d.id} src={d.raw!} name={d.name} tags={d.tags} onError={() => setBroken(true)} /></div>;
  if (d.mode === "pdf") return <iframe className="pv-frame" src={d.raw} title={"Preview of " + d.name} />;
  if (d.mode === "text") return <div className="pv-scroll"><pre className="pv-text">{d.text}</pre>{d.truncated && <p className="sub pv-pad">Only the start of the file is shown.</p>}</div>;
  if (d.mode === "table") return <Table sheets={d.sheets ?? []} id={d.id} />;
  if (d.mode === "doc") return <DocView id={d.id} blocks={d.blocks ?? []} images={d.images ?? 0} truncated={!!d.truncated} />;
  if (d.mode === "pages") return <Pages d={d} />;
  if (d.mode === "archive") return <Archive d={d} />;
  return <div className="pv-scroll"><p className="sub pv-pad">There is no picture or text to show for this kind of file, so here are its first bytes.</p><pre className="pv-text pv-hex">{d.hex}</pre></div>;
}

function Facts({ d, decide, hints }: { d: PreviewInfo; decide: (on: boolean, advance: boolean) => void; hints: boolean }) {
  const rise = useRise("dl > div", [d.id], { step: 40, lift: 6 });
  return (
    <footer className="pv-foot" ref={rise as React.RefObject<HTMLElement>}>
      {d.note && <p className="pv-note">{d.note}</p>}
      <dl>
        <div><dt>Size</dt><dd>{fmt(d.size)}</dd></div>
        <div><dt>Modified</dt><dd>{when(d.mtime)}</dd></div>
        <div><dt>Status</dt><dd><span className={"tag " + d.status}>{d.gone ? "Deleted from the PC" : label[d.status]}</span></dd></div>
        {!d.gone && <div><dt>Your choice</dt><dd>{d.selected ? "Will be backed up" : d.reviewed ? "Skipped" : "Waiting for your decision"}</dd></div>}
        {d.from_pc && <div><dt>From</dt><dd>{d.from_pc}</dd></div>}
        {d.source && <div><dt>Shown from</dt><dd>{d.source}</dd></div>}
        <div><dt>Backups</dt><dd>{d.backed.length ? d.backed.map(b => `${b.dest} on ${b.at}`).join(", ") : "Not backed up yet"}</dd></div>
      </dl>
      {!d.gone && (
        <div className="pv-act">
          <button type="button" className={d.selected ? "" : "primary"} onClick={() => decide(true, true)} title="Back up this file and go to the next (Enter)">{d.selected ? "Backed up, next" : "Back up"}<Kbd>Enter</Kbd></button>
          <button type="button" onClick={() => decide(false, true)} title="Skip this file and go to the next (S)">Skip<Kbd>S</Kbd></button>
        </div>
      )}
      {hints && (
        <p className="pv-keys" aria-hidden="true">
          <span><Kbd>←</Kbd><Kbd>→</Kbd>files</span><span><Kbd>F</Kbd>full screen</span><span><Kbd>I</Kbd>details</span><span><Kbd>?</Kbd>all keys</span>
        </p>
      )}
    </footer>
  );
}

export function PreviewHost() {
  const st = usePreviewState(); const calm = useReducedMotion();
  const open = !!st, id = st ? st.ids[st.i] : null;
  const [d, setD] = useState<PreviewInfo | null>(null); const [err, setErr] = useState("");
  const [full, setFull] = useState(false); const [facts, setFacts] = useState(true); const [zoom, setZoom] = useState(1); const [rot, setRot] = useState(0);
  const [flash, setFlash] = useState<{ text: string; n: number } | null>(null);
  const box = useRef<HTMLDivElement>(null); const from = useRef<HTMLElement | null>(null); const flashTimer = useRef(0);
  const n = st?.ids.length ?? 0, i = st?.i ?? 0;
  const prev = useRef(i); const dir = i >= prev.current ? 1 : -1;                   // which way we stepped, for the slide
  useEffect(() => { prev.current = i; }, [i]);
  const say = (text: string) => { window.clearTimeout(flashTimer.current); setFlash(f => ({ text, n: (f?.n ?? 0) + 1 })); flashTimer.current = window.setTimeout(() => setFlash(null), 1600); };

  // The file on screen stays until the next one has arrived, so stepping crossfades instead of flashing a blank.
  useEffect(() => {
    if (!id) return;
    let live = true;
    setErr(""); setZoom(1); setRot(0);
    const hit = cached(id);
    if (hit) setD(hit);
    else loadInfo(id).then(x => { if (live) setD(x); }).catch(e => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [id]);
  useEffect(() => {
    if (!d || !st || d.id !== id) return;
    const t = window.setTimeout(() => prefetch(d, st.ids, st.i), 220);          // after the file on screen has settled
    return () => window.clearTimeout(t);
  }, [d, id]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Back up or skip the file on screen, and (by default) move on to the next one. */
  const decide = async (on: boolean, advance: boolean) => {
    if (!d || d.gone || d.id !== id) return;
    try {
      await api("/api/files/select", "POST", { selected: on, ids: [d.id] });
      const patch = { selected: on ? 1 : 0, reviewed: true };
      patchCached(d.id, patch);
      setD(x => (x && x.id === d.id ? { ...x, ...patch } : x));
      window.dispatchEvent(new Event("files-changed"));                          // the lists and counts behind catch up
      say(on ? "Will be backed up" : "Skipped");
      if (advance && i < n - 1) stepPreview(1);
    } catch (e) { say("Could not save: " + (e as Error).message); }
  };
  const live = useRef({ decide, say, d, full, zoom, i, n });
  live.current = { decide, say, d, full, zoom, i, n };

  useEffect(() => {
    if (!open) return;
    from.current = document.activeElement as HTMLElement | null;
    setFull(false); setFacts(true);
    box.current?.focus({ preventScroll: true });                               // focus the window, not a button, so Enter is "back up" and not "close"
    const media = () => box.current?.querySelector<HTMLMediaElement>("audio, video") ?? null;
    const scroller = () => box.current?.querySelector<HTMLElement>(".pv-scroll, .pv-media.zoomed") ?? null;
    const scroll = (by: number | "top" | "end", page = false) => {
      const el = scroller(); if (!el) return;
      const top = by === "top" ? 0 : by === "end" ? el.scrollHeight : el.scrollTop + (page ? el.clientHeight * 0.9 : 1) * by;
      el.scrollTo({ top, behavior: calm ? "auto" : "smooth" });
    };
    const isImage = () => live.current.d?.mode === "image";
    const key = (e: KeyboardEvent) => {
      if (document.querySelector(".kb-back, .dialog-back")) return;            // the shortcut list or a question is on top
      const t = e.target as HTMLElement, k = e.key, L = live.current, m = media();
      if (k === "Escape") { e.preventDefault(); closePreview(); return; }
      if (k === "Tab") {                                                        // keep the focus inside the window
        const items = Array.from(box.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], [tabindex='0'], input") ?? []);
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        return;
      }
      if (e.ctrlKey || e.metaKey) {
        if (isImage() && (k === "+" || k === "=")) { e.preventDefault(); setZoom(z => Math.min(5, +(z + 0.5).toFixed(1))); }
        else if (isImage() && (k === "-" || k === "_")) { e.preventDefault(); setZoom(z => Math.max(1, +(z - 0.5).toFixed(1))); }
        else if (isImage() && k === "0") { e.preventDefault(); setZoom(1); }
        return;                                                                 // Ctrl+C and the rest stay the browser's
      }
      if (e.altKey) { if (k === "ArrowLeft") { e.preventDefault(); stepPreview(-1); } else if (k === "ArrowRight") { e.preventDefault(); stepPreview(1); } return; }
      if (typingIn(t)) return;                                                  // a slider or field has the key
      const control = onControl(t);                                             // a focused button handles Enter and Space itself
      if (k === "ArrowRight" || k === "ArrowLeft") {
        e.preventDefault();
        const sign = k === "ArrowRight" ? 1 : -1;
        if (e.shiftKey && m) m.currentTime = Math.max(0, Math.min(m.duration || 0, m.currentTime + 5 * sign));
        else stepPreview(sign);
      }
      else if (k === "Home") { e.preventDefault(); goPreview(0); }
      else if (k === "End") { e.preventDefault(); goPreview(L.n - 1); }
      else if (k === "Enter") { if (!control) { e.preventDefault(); void L.decide(true, true); } }
      else if (k === "b" || k === "B") { e.preventDefault(); void L.decide(true, false); }
      else if (k === "s" || k === "S") { e.preventDefault(); void L.decide(false, true); }
      else if (k === "ArrowDown" || k === "ArrowUp") {
        e.preventDefault();
        if (m) m.volume = Math.max(0, Math.min(1, +(m.volume + (k === "ArrowUp" ? 0.1 : -0.1)).toFixed(2)));
        else scroll(k === "ArrowDown" ? 72 : -72);
      }
      else if (k === "PageDown" || k === "PageUp") { e.preventDefault(); scroll(k === "PageDown" ? 1 : -1, true); }
      else if (k === " ") {
        if (control) return;
        e.preventDefault();
        if (m) { if (m.paused) void m.play(); else m.pause(); } else scroll(e.shiftKey ? -1 : 1, true);
      }
      else if (m && (k === "k" || k === "K")) { e.preventDefault(); if (m.paused) void m.play(); else m.pause(); }
      else if (m && (k === "j" || k === "J")) { e.preventDefault(); m.currentTime = Math.max(0, m.currentTime - 10); }
      else if (m && (k === "l" || k === "L")) { e.preventDefault(); m.currentTime = Math.min(m.duration || 0, m.currentTime + 10); }
      else if (m && (k === "m" || k === "M")) { e.preventDefault(); m.muted = !m.muted; }
      else if (m && (k === "[" || k === "]")) { e.preventDefault(); m.playbackRate = Math.max(0.25, Math.min(3, +(m.playbackRate + (k === "]" ? 0.25 : -0.25)).toFixed(2))); L.say(m.playbackRate + "x"); }
      else if (m && k >= "0" && k <= "9") { e.preventDefault(); if (m.duration) m.currentTime = (m.duration * Number(k)) / 10; }
      else if (isImage() && (k === "+" || k === "=")) { e.preventDefault(); setZoom(z => Math.min(5, +(z + 0.5).toFixed(1))); }
      else if (isImage() && (k === "-" || k === "_")) { e.preventDefault(); setZoom(z => Math.max(1, +(z - 0.5).toFixed(1))); }
      else if (isImage() && k === "0") { e.preventDefault(); setZoom(1); setRot(0); }
      else if (isImage() && (k === "r" || k === "R")) { e.preventDefault(); setRot(r => (r + 90) % 360); }
      else if (k === "f" || k === "F") { e.preventDefault(); setFull(f => !f); }
      else if (k === "i" || k === "I") { e.preventDefault(); setFacts(f => !f); }
      else if (k === "c" || k === "C") {
        e.preventDefault();
        const p = L.d?.path;
        if (p) navigator.clipboard?.writeText(p).then(() => L.say("Path copied"), () => L.say("Could not copy the path"));
      }
    };
    const mouse = (e: MouseEvent) => {                                           // back and forward buttons step through the files, a middle click closes
      if (e.button === 3 || e.button === 4) { e.preventDefault(); if (e.type === "mouseup") stepPreview(e.button === 3 ? -1 : 1); }
      else if (e.button === 1) { e.preventDefault(); if (e.type === "auxclick") closePreview(); }
    };
    const wheel = (e: WheelEvent) => {                                           // Ctrl and the wheel zoom a picture
      if (!(e.ctrlKey || e.metaKey) || live.current.d?.mode !== "image") return;
      e.preventDefault();
      setZoom(z => Math.max(1, Math.min(5, +(z + (e.deltaY < 0 ? 0.25 : -0.25)).toFixed(2))));
    };
    window.addEventListener("keydown", key);
    window.addEventListener("mousedown", mouse); window.addEventListener("mouseup", mouse); window.addEventListener("auxclick", mouse);
    const el = box.current; el?.addEventListener("wheel", wheel, { passive: false });
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("mousedown", mouse); window.removeEventListener("mouseup", mouse); window.removeEventListener("auxclick", mouse);
      el?.removeEventListener("wheel", wheel);
      from.current?.focus?.();
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const loading = !!id && (!d || d.id !== id) && !err;
  const ease = [0.16, 1, 0.3, 1] as [number, number, number, number];
  const slide = {
    enter: (k: number) => ({ opacity: 0, x: calm ? 0 : k * 24 }),
    center: { opacity: 1, x: 0, transition: { duration: calm ? 0 : 0.2, ease } },
    exit: (k: number) => ({ opacity: 0, x: calm ? 0 : -k * 16, transition: { duration: calm ? 0 : 0.08, ease: "easeIn" as const } }),
  };
  const fast = { duration: calm ? 0 : 0.14, ease };
  return (
    <AnimatePresence onExitComplete={() => { setD(null); setErr(""); clearInfoCache(); }}>
      {st && (
        <motion.div className="pv-back" key="pv" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: calm ? 0 : 0.16 }} onPointerDown={e => { if (e.target === e.currentTarget) closePreview(); }}>
          <motion.div ref={box} tabIndex={-1} className={"pv" + (full ? " full" : "")} role="dialog" aria-modal="true" aria-label={"Preview of " + (d?.name ?? "a file")}
            onDoubleClick={e => { if (!(e.target as HTMLElement).closest("audio, video, button, input, iframe, a, .ap, .pv-tabs, summary")) setFull(f => !f); }}
            initial={calm ? false : { opacity: 0, y: 22, scale: 0.975 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={calm ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.985 }}
            transition={calm ? { duration: 0 } : { type: "spring", stiffness: 460, damping: 38, mass: 0.9 }}>
            <header className="pv-head">
              <FileIcon name={d?.name ?? ""} />
              <div className="pv-title">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div key={d?.id ?? "x"} initial={{ opacity: 0, y: calm ? 0 : 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
                    <b>{d?.name ?? "Loading…"}</b>{d && <span className="sub path" title={d.path}><bdi>{d.path}</bdi></span>}
                  </motion.div>
                </AnimatePresence>
              </div>
              <span className="sub pv-count">{n > 1 ? `${i + 1} of ${n.toLocaleString()}` : ""}</span>
              <button type="button" className="quiet" onClick={() => stepPreview(-1)} disabled={i <= 0} aria-label="Previous file" title="Previous (left arrow, or the mouse back button)"><Icon name="chevron" className="ico pv-prev" /></button>
              <button type="button" className="quiet" onClick={() => stepPreview(1)} disabled={i >= n - 1} aria-label="Next file" title="Next (right arrow, or the mouse forward button)"><Icon name="chevron" className="ico pv-next" /></button>
              <button type="button" className="quiet" onClick={() => setFull(f => !f)} aria-pressed={full} aria-label="Full screen" title="Full screen (F)"><Icon name="expand" /></button>
              <button type="button" onClick={closePreview} aria-label="Close the preview" title="Close (Esc)"><Icon name="cancel" /></button>
              <span className={"pv-load" + (loading ? " on" : "")} aria-hidden="true" />
            </header>
            <div className="pv-body" aria-live="polite" aria-busy={loading}>
              {err && <div className="pv-center"><p className="err">Could not load the preview: {err}</p></div>}
              {!err && !d && <div className="pv-center"><p className="sub">Loading the preview…</p></div>}
              <AnimatePresence mode="wait" initial={false} custom={dir}>
                {d && !err && (
                  <motion.div className="pv-fill" key={d.id} custom={dir} variants={slide} initial="enter" animate="center" exit="exit">
                    <Body d={d} zoom={zoom} rot={rot} />
                  </motion.div>
                )}
              </AnimatePresence>
              <AnimatePresence>
                {flash && <motion.div key={flash.n} className="pv-flash" role="status" initial={{ opacity: 0, y: calm ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: calm ? 0 : 0.14 }}>{flash.text}</motion.div>}
              </AnimatePresence>
            </div>
            {d && !err ? (facts ? <Facts key={d.id} d={d} decide={decide} hints /> : <footer className="pv-foot pv-foot-min"><button type="button" className="quiet" onClick={() => setFacts(true)} title="Show the details (I)">Details<Kbd>I</Kbd></button></footer>) : <footer className="pv-foot" />}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
