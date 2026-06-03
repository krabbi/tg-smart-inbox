/**
 * Main.ts — placeholder entry point for the Foldkit TypeScript SPA.
 *
 * This file follows the Elm Architecture (Model / update / view) pattern
 * that Foldkit uses. For now it renders a simple "loading…" state so the
 * build pipeline can be verified end-to-end before any real UI logic is added.
 */

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

interface Model {
  status: "loading" | "ready";
}

const initialModel: Model = { status: "loading" };

// ---------------------------------------------------------------------------
// Msg (union of all possible messages)
// ---------------------------------------------------------------------------

type Msg = { type: "AppReady" };

// ---------------------------------------------------------------------------
// update
// ---------------------------------------------------------------------------

function update(model: Model, msg: Msg): Model {
  switch (msg.type) {
    case "AppReady":
      return { ...model, status: "ready" };
  }
}

// ---------------------------------------------------------------------------
// view
// ---------------------------------------------------------------------------

function view(model: Model): string {
  switch (model.status) {
    case "loading":
      return "loading…";
    case "ready":
      return "App ready.";
  }
}

// ---------------------------------------------------------------------------
// Runtime (minimal — no framework dependency yet)
// ---------------------------------------------------------------------------

function mount(rootId: string): void {
  const root = document.getElementById(rootId);
  if (root === null) {
    throw new Error(`mount: element #${rootId} not found`);
  }

  let model = initialModel;

  function render(): void {
    root!.textContent = view(model);
  }

  function dispatch(msg: Msg): void {
    model = update(model, msg);
    render();
  }

  // Initial render
  render();

  // Simulate async initialisation completing
  window.addEventListener("load", () => {
    dispatch({ type: "AppReady" });
  });
}

mount("app");
