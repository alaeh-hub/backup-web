import { useEffect, useState } from "react";
import { INSTALLER_URL, RELEASES_API } from "./hosted";
import { Icon } from "./ui";

/** The only page a deployed site shows: the app cannot see your files from a server, so it is downloaded and run on the PC. */
export function Download() {
  const [version, setVersion] = useState("");
  useEffect(() => {
    fetch(RELEASES_API).then(r => (r.ok ? r.json() : null)).then(d => d?.tag_name && setVersion(String(d.tag_name))).catch(() => { /* the button works without it */ });
  }, []);
  return (
    <main className="dl">
      <img className="logo" src="/static/ala-eh-logo.png" alt="Ala Eh! Food Products" width={88} height={88} />
      <h1>File Backup</h1>
      <p className="sub">Back up the files on your PC to an external drive.</p>
      <a className="btn primary dl-btn" href={INSTALLER_URL} download><Icon name="download" />Download for Windows</a>
      <p className="sub">{version ? `Version ${version.replace(/^v/i, "")} · ` : ""}Windows 10 and 11</p>
      <p className="sub dl-note">Run the downloaded file to install. If Windows shows a warning, choose <b>More info</b>, then <b>Run anyway</b>.</p>
    </main>
  );
}
