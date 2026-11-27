/** Helpers every keyboard shortcut in the app shares. */

/** True while the person is typing in a field: single-key shortcuts must stay out of the way then. */
export function typingIn(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName !== "INPUT") return false;
  return !/^(checkbox|radio|button|submit|range)$/.test((el as HTMLInputElement).type);
}

/** True when the key press is for something that handles Enter or Space itself (a button, a link, a summary). */
export const onControl = (target: EventTarget | null) => !!(target as HTMLElement | null)?.closest?.("button, a[href], summary, [role='button'], [role='tab'], select");

/** A window on top of the page (dialog, preview, shortcut list): the page's own shortcuts wait. */
export const modalOpen = () => !!document.querySelector(".dialog-back, .pv-back, .kb-back");

export const plain = (e: KeyboardEvent) => !e.ctrlKey && !e.metaKey && !e.altKey;

// ---------------------------------------------------------------- the row cursor: j and k move it, Enter opens, x chooses

const visible = (el: HTMLElement) => el.getClientRects().length > 0;

/** Rows of the screen that can be acted on: a file (preview button) or a folder or file with a switch. */
export function cursorRows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("main.content :is(li, tr)"))
    .filter(r => visible(r) && !r.querySelector(":is(li, tr)") && r.querySelector(".pv-btn, input[type='checkbox'], .linkish"));
}

export const cursorRow = () => document.querySelector<HTMLElement>("main.content [data-kb]");

export function clearCursor() { document.querySelectorAll("[data-kb]").forEach(e => e.removeAttribute("data-kb")); }

export function moveCursor(step: number | "first" | "last") {
  const rows = cursorRows();
  if (!rows.length) return false;
  const at = rows.findIndex(r => r.hasAttribute("data-kb"));
  const next = step === "first" ? 0 : step === "last" ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, (at < 0 ? (step > 0 ? -1 : rows.length) : at) + step));
  clearCursor();
  const active = document.activeElement as HTMLElement | null;
  if (active && active !== document.body && !rows[next].contains(active)) active.blur();       // so Enter acts on the cursor row, not on the last button clicked
  rows[next].setAttribute("data-kb", "");
  rows[next].scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  return true;
}

/** Enter on the cursor row: open the file's preview, or step into the folder. */
export function openCursor() {
  const row = cursorRow();
  if (!row) return false;
  (row.querySelector<HTMLElement>(".pv-btn") ?? row.querySelector<HTMLElement>(".linkish"))?.click();
  return true;
}

/** x on the cursor row: choose or skip it (its switch or check box). */
export function toggleCursor() {
  const box = cursorRow()?.querySelector<HTMLInputElement>("input[type='checkbox']");
  box?.click();
  return !!box;
}

/** Put the cursor on the first row of the screen (from the search box, for example). */
export function focusList() {
  (document.activeElement as HTMLElement | null)?.blur?.();
  return moveCursor("first");
}

/** The search field of the current screen. */
export function focusSearch() {
  const el = document.querySelector<HTMLInputElement>("main.content input[type='search'], main.content .searchbox input");
  el?.focus();
  el?.select();
  return !!el;
}
