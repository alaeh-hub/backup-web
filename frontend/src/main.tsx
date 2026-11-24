import { createRoot } from "react-dom/client";
import App from "./App";
import { Download } from "./Download";
import { SHOW_DOWNLOAD } from "./hosted";
import "./styles.css";
createRoot(document.getElementById("root")!).render(SHOW_DOWNLOAD ? <Download /> : <App />);
