import { ReactNode, useId } from "react";

/** One entry of a panel's section index: its name, and a short live fact about it (how many, on or off). */
export interface PanelItem { key: string; label: string; hint?: string }

/** A screen split into sections: an index on the left (a strip across the top on a narrow screen) and one section at a time. */
export function Panel({ items, current, onChange, label, children }: { items: PanelItem[]; current: string; onChange: (key: string) => void; label: string; children: ReactNode }) {
  return (
    <div className="panel">
      <nav className="panel-nav" aria-label={label}>
        {items.map(i => (
          <button key={i.key} type="button" aria-current={current === i.key ? "true" : undefined} onClick={() => onChange(i.key)}>
            <b>{i.label}</b>{i.hint && <span className="hint">{i.hint}</span>}
          </button>
        ))}
      </nav>
      <div className="panel-body">{children}</div>
    </div>
  );
}

/** One section: its name, one sentence about it, and (on the right) a status such as "Saved automatically". */
export function Group({ title, lead, aside, children }: { title: string; lead?: string; aside?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section className="group" aria-labelledby={id}>
      <header className="group-head">
        <div><h2 id={id}>{title}</h2>{lead && <p className="sub">{lead}</p>}</div>
        {aside}
      </header>
      {children}
    </section>
  );
}

/** A cluster of related rows inside a section, under its own small heading. */
export function Cluster({ title, children }: { title?: string; children: ReactNode }) {
  return <div className="cluster">{title && <h3>{title}</h3>}{children}</div>;
}

/** One setting: what it is and what it does on the left, the control on the right (or underneath, for a wide one). */
export function Row({ title, desc, wide, off, children }: { title: string; desc?: ReactNode; wide?: boolean; off?: boolean; children?: ReactNode }) {
  return (
    <div className={"srow" + (wide ? " wide" : "") + (off ? " off" : "")}>
      <div className="srow-text"><b>{title}</b>{desc && <span className="sub">{desc}</span>}</div>
      {children && <div className="srow-ctl">{children}</div>}
    </div>
  );
}

/** The on/off switch the rest of the app uses, with the name a screen reader needs. */
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (on: boolean) => void; label: string }) {
  return <label className="switch"><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} aria-label={label} /><span /></label>;
}
