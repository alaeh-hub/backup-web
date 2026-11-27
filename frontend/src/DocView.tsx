import { Fragment } from "react";
import { DocBlock, DocRun } from "./api";
import { useRise } from "./ui";

/** A Word document drawn like a page: the formatting it was written with, its headings, lists, tables and pictures.
 *  The server sends a plain model (never HTML), so nothing in the file can run; pictures are asked for one by one. */
const HEX = /^[0-9A-Fa-f]{6}$/;
const px = (pt: number | undefined) => (pt === undefined ? undefined : `${pt}pt`);

function Run({ r, id, k }: { r: DocRun; id: string; k: number }) {
  if (r.br) return <br key={k} />;
  if (r.img) {
    const style = r.w ? { width: r.w + "px" } : undefined;
    return <img key={k} className="dv-img" loading="lazy" decoding="async" src={`/api/preview/${id}/part?name=${encodeURIComponent(r.img)}`} alt={r.alt ?? ""} style={style} />;
  }
  const style: React.CSSProperties = {};
  if (r.b) style.fontWeight = 700;
  if (r.i) style.fontStyle = "italic";
  const deco = [r.u ? "underline" : "", r.s ? "line-through" : ""].filter(Boolean).join(" ");
  if (deco) style.textDecoration = deco;
  if (r.c && HEX.test(r.c) && r.c !== "FFFFFF") style.color = "#" + r.c;
  if (r.hl && HEX.test(r.hl)) style.backgroundColor = "#" + r.hl;
  if (r.sz) style.fontSize = r.sz + "pt";
  if (r.caps) style.textTransform = "uppercase";
  if (r.f === "serif") style.fontFamily = "var(--font-serif)";
  if (r.f === "mono") style.fontFamily = "var(--font-mono)";
  const inner = <span style={style}>{r.x}</span>;
  return r.va === "superscript" ? <sup key={k}>{inner}</sup> : r.va === "subscript" ? <sub key={k}>{inner}</sub> : <Fragment key={k}>{inner}</Fragment>;
}

function Para({ b, id }: { b: Extract<DocBlock, { t: "p" }>; id: string }) {
  const onlyPictures = b.runs.length > 0 && b.runs.every(r => r.img);
  const style: React.CSSProperties = { textAlign: onlyPictures ? "center" : (b.al as React.CSSProperties["textAlign"]), marginTop: px(b.before), marginBottom: px(b.after) };
  const body = b.runs.map((r, k) => <Run key={k} k={k} r={r} id={id} />);
  const empty = !b.runs.length && b.label === undefined;
  if (b.label !== undefined) {
    const hang = b.hang ?? 18, left = (b.left ?? 36 + (b.lvl ?? 0) * 18) - hang;
    return <p className={"dv-li" + (b.box ? " dv-box" : "")} style={{ ...style, paddingLeft: Math.max(left, 0) + "pt" }}><span className="dv-label" style={{ minWidth: hang + "pt" }}>{b.label}</span><span className="dv-li-text">{body}</span></p>;
  }
  if (b.left || b.first) style.paddingLeft = px(Math.max((b.left ?? 0) + Math.max(b.first ?? 0, 0), 0));
  const cls = (b.box ? "dv-box " : "") + (empty ? "dv-gap" : "");
  if (b.h === "title") return <h1 className={"dv-title " + cls} style={style}>{body}</h1>;
  if (b.h && /^h[1-6]$/.test(b.h)) {
    const H = b.h as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
    return <H className={"dv-h " + cls} style={style}>{body}</H>;
  }
  if (b.h === "subtitle") return <p className={"dv-sub " + cls} style={style}>{body}</p>;
  return <p className={cls || undefined} style={style}>{empty ? " " : body}</p>;
}

function Block({ b, id }: { b: DocBlock; id: string }) {
  if (b.t === "pagebreak") return <div className="dv-break" aria-hidden="true" />;
  if (b.t === "table") {
    return (
      <table className={"dv-table" + (b.grid ? " grid" : "")}>
        <tbody>{b.rows.map((row, i) => (
          <tr key={i}>{row.map((c, j) => (
            <td key={j} colSpan={c.span} className={c.cont ? "cont" : undefined} style={c.fill && HEX.test(c.fill) && c.fill !== "FFFFFF" ? { backgroundColor: "#" + c.fill } : undefined}>
              {c.blocks.map((x, k) => <Block key={k} b={x} id={id} />)}
            </td>
          ))}</tr>
        ))}</tbody>
      </table>
    );
  }
  return <Para b={b} id={id} />;
}

export function DocView({ id, blocks, images, truncated }: { id: string; blocks: DocBlock[]; images: number; truncated: boolean }) {
  const rise = useRise(".dv > *", [id], { max: 14, step: 36, lift: 12 });
  return (
    <div className="pv-scroll pv-docwrap" ref={rise}>
      {images > 12 && <p className="sub pv-note-top">{images} pictures in this document. They load as you scroll.</p>}
      <article className="dv">{blocks.map((b, i) => <Block key={i} b={b} id={id} />)}</article>
      {truncated && <p className="sub pv-note-top">Only the first part of this document is shown.</p>}
    </div>
  );
}
