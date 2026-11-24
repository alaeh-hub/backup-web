import { createRoot } from "react-dom/client";
import App from "./App";
import { Download } from "./Download";
import { SHOW_DOWNLOAD } from "./hosted";
import "@fontsource-variable/bricolage-grotesque";   // the fonts are part of the app: no request leaves this PC to draw the page
import "@fontsource-variable/hanken-grotesk";
import "./styles.css";
createRoot(document.getElementById("root")!).render(SHOW_DOWNLOAD ? <Download /> : <App />);
