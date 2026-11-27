import { Icon } from "./ui";
import { focusList } from "./keys";
import { searchHelp } from "./smart";
import { useStored } from "./api";

/** The search field every list uses: an icon, a clear button, the smart-search tips on hover, and (with saveKey) saved searches kept as chips. */
export function SearchBox({ value, onChange, placeholder, label, help = searchHelp, saveKey }: { value: string; onChange: (v: string) => void; placeholder: string; label: string; help?: string; saveKey?: string }) {
  const [saved, setSaved] = useStored<string[]>("searches." + (saveKey ?? "none"), []);
  const q = value.trim(), can = !!saveKey && !!q && !saved.includes(q);
  return (
    <div className="sb" title={help}>
      <div className="searchbox">
        <Icon name="search" />
        <input type="search" aria-label={label} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} onKeyDown={e => {
          if (e.key === "Escape") { e.preventDefault(); if (value) onChange(""); else (e.target as HTMLElement).blur(); }       // first Esc clears the search, the next leaves the box
          else if (e.key === "ArrowDown" || (e.key === "Enter" && !e.shiftKey)) { if (focusList()) e.preventDefault(); }          // on to the results
        }} />
        {value && <button type="button" className="quiet" aria-label="Clear the search" onClick={() => onChange("")}><Icon name="cancel" /></button>}
      </div>
      {saveKey && (can || saved.length > 0) && (
        <div className="sb-saved" role="group" aria-label="Saved searches">
          {saved.map(s => (
            <span key={s} className={"sb-chip" + (s === q ? " on" : "")}>
              <button type="button" onClick={() => onChange(s)} title="Use this search">{s}</button>
              <button type="button" className="x" aria-label={"Remove the saved search " + s} onClick={() => setSaved(saved.filter(x => x !== s))}><Icon name="cancel" /></button>
            </span>
          ))}
          {can && <button type="button" className="quiet" onClick={() => setSaved([...saved, q].slice(-8))}>Save this search</button>}
        </div>
      )}
    </div>
  );
}
