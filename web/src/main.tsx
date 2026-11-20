import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";
import { PRODUCT_NAME } from "./brand";
import { ErrorBoundary } from "./components/common/error-boundary";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/highlight.css";

document.title = PRODUCT_NAME;

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("The page is missing its #root element");
}

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
);
