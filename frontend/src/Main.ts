/**
 * Main.ts — Foldkit application entry point.
 *
 * Wires the Elm Architecture triad: Model / update / view.
 *
 * Init behaviour:
 *   - No JWT in localStorage → render login placeholder immediately, no API call.
 *   - JWT present → call GET /api/auth/me to validate:
 *       200  → dispatch MeLoaded (sets auth to authenticated)
 *       401  → clearJwt() is called inside apiRequest; dispatches SessionExpired
 *
 * SessionExpired → clears JWT from localStorage, returns to unauthenticated state.
 *
 * Item list behaviour:
 *   - On NavigateTo (item routes) → fetch items for that route.
 *   - On SearchItems → fetch items with q param.
 *   - On ClearSearch → fetch items without q param.
 *   - On ChangePage → fetch items for the new page.
 *   - On SelectItem → fetch full item detail via GET /api/items/{id}.
 *   - On ConfirmDeleteItem → DELETE /api/items/{id}.
 *   - On ConfirmBulkDelete → DELETE /api/items (bulk).
 */

import { getJwt, setJwt, clearJwt, type Command } from "./api/client.ts";
import { apiRequest } from "./api/client.ts";
import type { MeResponse, TelegramLoginPayload, ItemType } from "./api/types.ts";
import { initialModel, resetItemListState, type Model } from "./Model.ts";
import type { Msg } from "./Messages.ts";
import { view, attachListeners } from "./views/Layout.ts";
import { postTelegramAuth } from "./api/auth.ts";
import {
  getItems,
  getItem,
  deleteItem,
  bulkDeleteItems,
  type ItemsMsg,
} from "./api/items.ts";

// ---------------------------------------------------------------------------
// Route → ItemType mapping
// ---------------------------------------------------------------------------

/**
 * Map a sidebar route to an API item type filter.
 * "all" and "reminders" return undefined (no type filter).
 */
function routeToItemType(route: string): ItemType | undefined {
  switch (route) {
    case "tasks":
      return "task";
    case "notes":
      return "note";
    case "links":
      return "link";
    case "ideas":
      return "idea";
    default:
      return undefined;
  }
}

/** Return true when the route maps to an item list (not the reminders panel). */
function isItemRoute(route: string): boolean {
  return route === "all" || route === "tasks" || route === "notes" || route === "links" || route === "ideas";
}

// ---------------------------------------------------------------------------
// Command helpers
// ---------------------------------------------------------------------------

/**
 * Build a Command that validates the stored JWT via GET /api/auth/me.
 * On success dispatches MeLoaded; on failure dispatches SessionExpired
 * (which is the canonical Msg for 401 responses from apiRequest).
 */
function validateStoredJwt(): Command<Msg> {
  return apiRequest<Msg, MeResponse>(
    "/api/auth/me",
    { method: "GET" },
    (data) => ({ type: "MeLoaded", user: data }),
    (err) => {
      if (err.type === "SessionExpired") {
        return { type: "SessionExpired" };
      }
      if (err.type === "AccessDenied") {
        return { type: "AccessDenied" };
      }
      // Any other HTTP error on startup — treat as session gone.
      return { type: "SessionExpired" };
    },
  );
}

/**
 * Build a Command<Msg> that POSTs the Telegram Login Widget payload to the
 * backend and then fetches /api/auth/me with the returned JWT to obtain the
 * full user object.
 *
 * Flow:
 *   POST /api/auth/telegram  → token
 *   GET  /api/auth/me        → user  → dispatch AuthSuccess(token, user)
 *
 * Error mapping:
 *   403  → AuthFailed("Access denied — you are not on the allowed list")
 *   any  → AuthFailed("Login failed — invalid or expired data, please try again")
 */
function telegramAuthCommand(payload: TelegramLoginPayload): Command<Msg> {
  return {
    run(dispatch) {
      postTelegramAuth(payload).run((authMsg) => {
        if (authMsg.type === "AuthSuccess") {
          // Store the JWT so the follow-up GET /api/auth/me can attach it.
          setJwt(authMsg.token);
          apiRequest<Msg, MeResponse>(
            "/api/auth/me",
            { method: "GET" },
            (data) => ({ type: "AuthSuccess", token: authMsg.token, user: data }),
            (err) => {
              if (err.type === "AccessDenied") {
                return {
                  type: "AuthFailed",
                  reason: "Access denied — you are not on the allowed list",
                };
              }
              return {
                type: "AuthFailed",
                reason: "Login failed — invalid or expired data, please try again",
              };
            },
          ).run(dispatch);
        } else {
          // authMsg.type === "AuthError"
          const err = authMsg.err;
          if (err.type === "AccessDenied") {
            dispatch({
              type: "AuthFailed",
              reason: "Access denied — you are not on the allowed list",
            });
          } else {
            dispatch({
              type: "AuthFailed",
              reason: "Login failed — invalid or expired data, please try again",
            });
          }
        }
      });
    },
  };
}

/**
 * Build a Command that fetches items for the current list state.
 * Adapts ItemsMsg into Msg so the runtime dispatch loop stays typed.
 */
function fetchItemsCommand(
  route: string,
  page: number,
  searchQuery: string,
): Command<Msg> {
  const itemType = routeToItemType(route);
  const cmd = getItems({
    type: itemType,
    page,
    q: searchQuery !== "" ? searchQuery : undefined,
  });
  return {
    run(dispatch) {
      cmd.run((itemsMsg: ItemsMsg) => {
        dispatch(itemsMsg as unknown as Msg);
      });
    },
  };
}

/** Build a Command that fetches one item by id. */
function fetchItemCommand(id: string): Command<Msg> {
  const cmd = getItem(id);
  return {
    run(dispatch) {
      cmd.run((itemsMsg: ItemsMsg) => {
        dispatch(itemsMsg as unknown as Msg);
      });
    },
  };
}

/** Build a Command that deletes one item by id. */
function deleteItemCommand(id: string): Command<Msg> {
  const cmd = deleteItem(id);
  return {
    run(dispatch) {
      cmd.run((itemsMsg: ItemsMsg) => {
        dispatch(itemsMsg as unknown as Msg);
      });
    },
  };
}

/** Build a Command that bulk-deletes items by ids. */
function bulkDeleteCommand(ids: string[]): Command<Msg> {
  const cmd = bulkDeleteItems(ids);
  return {
    run(dispatch) {
      cmd.run((itemsMsg: ItemsMsg) => {
        dispatch(itemsMsg as unknown as Msg);
      });
    },
  };
}

// ---------------------------------------------------------------------------
// update — pure function: (Model, Msg) → { model: Model, commands: Command<Msg>[] }
// ---------------------------------------------------------------------------

/** Result of update(): new model plus any commands to run. */
interface UpdateResult {
  model: Model;
  commands: Command<Msg>[];
}

/**
 * Return the next Model and any side-effect commands given the current Model
 * and a dispatched Msg. All state transitions live here; no side effects.
 */
function update(model: Model, msg: Msg): UpdateResult {
  switch (msg.type) {
    // -----------------------------------------------------------------------
    // Auth
    // -----------------------------------------------------------------------

    case "TelegramLoginSuccess":
      return {
        model: { ...model, isLoading: true, error: null },
        commands: [],
      };

    case "AuthSuccess":
      setJwt(msg.token);
      return {
        model: {
          ...model,
          auth: { tag: "authenticated", token: msg.token, user: msg.user },
          isLoading: false,
          error: null,
          // Reset item list and immediately load the default "all" route.
          itemList: { ...resetItemListState(), isLoading: true },
        },
        commands: [fetchItemsCommand("all", 1, "")],
      };

    case "MeLoaded":
      return {
        model: {
          ...model,
          auth: {
            tag: "authenticated",
            token: getJwt() ?? "",
            user: msg.user,
          },
          isLoading: false,
          error: null,
          itemList: { ...resetItemListState(), isLoading: true },
        },
        commands: [fetchItemsCommand(model.currentRoute, 1, "")],
      };

    case "AuthFailed":
      return {
        model: {
          ...model,
          auth: { tag: "unauthenticated" },
          isLoading: false,
          error: msg.reason,
        },
        commands: [],
      };

    case "SessionExpired":
      clearJwt();
      return {
        model: {
          ...model,
          auth: { tag: "unauthenticated" },
          isLoading: false,
          error: null,
        },
        commands: [],
      };

    case "AccessDenied":
      return {
        model: {
          ...model,
          auth: { tag: "unauthenticated" },
          isLoading: false,
          error: "Access denied — your account is not whitelisted.",
        },
        commands: [],
      };

    // -----------------------------------------------------------------------
    // Navigation
    // -----------------------------------------------------------------------

    case "NavigateTo": {
      const newModel: Model = {
        ...model,
        currentRoute: msg.route,
        itemList: {
          ...resetItemListState(),
          isLoading: isItemRoute(msg.route),
        },
      };
      const commands: Command<Msg>[] = isItemRoute(msg.route)
        ? [fetchItemsCommand(msg.route, 1, "")]
        : [];
      return { model: newModel, commands };
    }

    // -----------------------------------------------------------------------
    // Global UI
    // -----------------------------------------------------------------------

    case "ClearError":
      return { model: { ...model, error: null }, commands: [] };

    // -----------------------------------------------------------------------
    // Item list — data loaded
    // -----------------------------------------------------------------------

    case "ItemsLoaded":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            items: msg.data.items,
            page: msg.data.page,
            total_pages: msg.data.total_pages,
            isLoading: false,
          },
        },
        commands: [],
      };

    case "ItemLoaded":
      // Store loaded detail in a side-channel: we carry it in a new field.
      // The view reads model.itemList.loadedDetail.
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            // We keep the loaded detail in loadedDetail (added to ItemListState below).
            loadedDetail: msg.data,
            isLoading: false,
          },
        },
        commands: [],
      };

    case "ItemsError":
      return {
        model: {
          ...model,
          itemList: { ...model.itemList, isLoading: false },
          error:
            msg.err.type === "SessionExpired"
              ? null
              : msg.err.type === "AccessDenied"
                ? "Access denied."
                : `Request failed (HTTP ${(msg.err as { type: "HttpError"; status: number }).status}).`,
        },
        commands:
          msg.err.type === "SessionExpired"
            ? [{ run: (d) => d({ type: "SessionExpired" }) }]
            : [],
      };

    // -----------------------------------------------------------------------
    // Item list — selection
    // -----------------------------------------------------------------------

    case "SelectItem":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            selectedItemId: msg.id,
            loadedDetail: null,
            isLoading: true,
          },
        },
        commands: [fetchItemCommand(msg.id)],
      };

    case "BackToList":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            selectedItemId: null,
            loadedDetail: null,
          },
        },
        commands: [],
      };

    // -----------------------------------------------------------------------
    // Item list — search
    // -----------------------------------------------------------------------

    case "SearchItems":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            searchQuery: msg.q,
            page: 1,
            isLoading: true,
            checkedIds: new Set(),
          },
        },
        commands: [fetchItemsCommand(model.currentRoute, 1, msg.q)],
      };

    case "ClearSearch":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            searchQuery: "",
            page: 1,
            isLoading: true,
            checkedIds: new Set(),
          },
        },
        commands: [fetchItemsCommand(model.currentRoute, 1, "")],
      };

    // -----------------------------------------------------------------------
    // Item list — pagination
    // -----------------------------------------------------------------------

    case "ChangePage":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            page: msg.page,
            isLoading: true,
            checkedIds: new Set(),
          },
        },
        commands: [fetchItemsCommand(model.currentRoute, msg.page, model.itemList.searchQuery)],
      };

    // -----------------------------------------------------------------------
    // Item list — checkbox
    // -----------------------------------------------------------------------

    case "ToggleItemCheck": {
      const next = new Set(model.itemList.checkedIds);
      if (next.has(msg.id)) {
        next.delete(msg.id);
      } else {
        next.add(msg.id);
      }
      return {
        model: { ...model, itemList: { ...model.itemList, checkedIds: next } },
        commands: [],
      };
    }

    // -----------------------------------------------------------------------
    // Item list — single delete
    // -----------------------------------------------------------------------

    case "RequestDeleteItem":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            deleteConfirm: { tag: "single", id: msg.id },
          },
        },
        commands: [],
      };

    case "ConfirmDeleteItem": {
      if (model.itemList.deleteConfirm.tag !== "single") {
        return { model, commands: [] };
      }
      const { id } = model.itemList.deleteConfirm;
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            deleteConfirm: { tag: "none" },
            isLoading: true,
          },
        },
        commands: [deleteItemCommand(id)],
      };
    }

    case "ItemDeleted":
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            items: model.itemList.items.filter((i) => i.id !== msg.id),
            checkedIds: (() => {
              const s = new Set(model.itemList.checkedIds);
              s.delete(msg.id);
              return s;
            })(),
            isLoading: false,
            deleteConfirm: { tag: "none" },
          },
        },
        commands: [],
      };

    // -----------------------------------------------------------------------
    // Item list — bulk delete
    // -----------------------------------------------------------------------

    case "RequestBulkDelete": {
      const ids = Array.from(model.itemList.checkedIds);
      if (ids.length === 0) return { model, commands: [] };
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            deleteConfirm: { tag: "bulk", ids },
          },
        },
        commands: [],
      };
    }

    case "ConfirmBulkDelete": {
      if (model.itemList.deleteConfirm.tag !== "bulk") {
        return { model, commands: [] };
      }
      const { ids } = model.itemList.deleteConfirm;
      // Keep deleteConfirm as "bulk" so ItemsBulkDeleted knows which ids to remove.
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            isLoading: true,
          },
        },
        commands: [bulkDeleteCommand(ids)],
      };
    }

    case "ItemsBulkDeleted": {
      // deleteConfirm still holds the bulk ids (set in RequestBulkDelete, preserved
      // through ConfirmBulkDelete) — use them to filter the list.
      const deletedSet = new Set(
        model.itemList.deleteConfirm.tag === "bulk"
          ? model.itemList.deleteConfirm.ids
          : [],
      );
      return {
        model: {
          ...model,
          itemList: {
            ...model.itemList,
            items: model.itemList.items.filter((i) => !deletedSet.has(i.id)),
            checkedIds: new Set(),
            isLoading: false,
            deleteConfirm: { tag: "none" },
            feedback: `Deleted ${msg.deleted} item${msg.deleted === 1 ? "" : "s"}.`,
          },
        },
        commands: [],
      };
    }

    case "CancelDelete":
      return {
        model: {
          ...model,
          itemList: { ...model.itemList, deleteConfirm: { tag: "none" } },
        },
        commands: [],
      };

    case "ClearItemFeedback":
      return {
        model: { ...model, itemList: { ...model.itemList, feedback: null } },
        commands: [],
      };
  }
}

// ---------------------------------------------------------------------------
// Runtime — minimal Foldkit-style loop
// ---------------------------------------------------------------------------

/**
 * Mount the application on the DOM element with the given id.
 * Sets up the render loop and runs the init command if a JWT is present.
 */
function mount(rootId: string): void {
  const root = document.getElementById(rootId);
  if (root === null) {
    throw new Error(`mount: element #${rootId} not found`);
  }

  let model = initialModel;

  function render(): void {
    root!.innerHTML = view(model);
    attachListeners(root!, dispatch, model);
  }

  function dispatch(msg: Msg): void {
    const result = update(model, msg);
    model = result.model;
    render();
    for (const cmd of result.commands) {
      runCommand(cmd);
    }
    // Fire side-effecting commands that cannot live in the pure update().
    if (msg.type === "TelegramLoginSuccess") {
      runCommand(telegramAuthCommand(msg.payload));
    }
  }

  function runCommand(cmd: Command<Msg>): void {
    cmd.run(dispatch);
  }

  // Initial render
  render();

  // If a JWT is already stored, validate it immediately — no extra network
  // call if the token is absent.
  const storedToken = getJwt();
  if (storedToken !== null) {
    model = { ...model, isLoading: true };
    render();
    runCommand(validateStoredJwt());
  }
}

mount("app");
