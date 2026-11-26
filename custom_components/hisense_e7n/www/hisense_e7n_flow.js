/**
 * Hisense E7N options dialog: put Back at the bottom left and keep Submit
 * at the bottom right (same footer as TCL 添加输入源).
 *
 * Home Assistant renders dialog-data-entry-flow inside shadow roots, so this
 * script walks them. The Python schema accepts {go_back: true} from Back
 * without other fields. Menu 返回 rows stay as a fallback if this script
 * does not run.
 */
(function () {
  if (window.__hisenseE7nFlowUi) return;
  window.__hisenseE7nFlowUi = true;

  const DOMAIN = "hisense_e7n";
  const DIALOG_SEL = "dialog-data-entry-flow";
  const MARK = "data-hisense-e7n";
  const HIDE_MARK = "data-hisense-e7n-hide";
  const HIDDEN_MENU = {
    sources: ["sources_done"],
    source_seq_kind: ["source_seq_kind_back"],
  };

  function isZh(hass) {
    const lang = String(
      hass?.language || hass?.locale?.language || ""
    ).toLowerCase();
    return lang.startsWith("zh");
  }

  function labels(hass) {
    return isZh(hass)
      ? { save: "保存", back: "返回", submit: "提交" }
      : { save: "Save", back: "Back", submit: "Submit" };
  }

  function deepQuery(root, selector) {
    const out = [];
    const visit = (node) => {
      if (!node) return;
      const start = node.shadowRoot || node;
      if (!start.querySelectorAll) return;
      try {
        start.querySelectorAll(selector).forEach((el) => out.push(el));
      } catch (_err) {
        /* ignore invalid selector on this node */
      }
      start.querySelectorAll("*").forEach((el) => {
        if (el.shadowRoot) visit(el);
      });
    };
    visit(root);
    return out;
  }

  function readProp(obj, names) {
    if (!obj) return undefined;
    for (const name of names) {
      try {
        const value = obj[name];
        if (value !== undefined && value !== null) return value;
      } catch (_err) {
        /* ignore */
      }
    }
    return undefined;
  }

  function menuItemId(el) {
    return el.step || el.value || el.getAttribute?.("value") || "";
  }

  function hideEl(el) {
    if (!el || el.getAttribute(HIDE_MARK) === "1") return;
    el.setAttribute(HIDE_MARK, "1");
    el.hidden = true;
    el.setAttribute("hidden", "");
    el.setAttribute("aria-hidden", "true");
    el.style.setProperty("display", "none", "important");
  }

  function restoreHidden(dialog) {
    deepQuery(dialog, `[${HIDE_MARK}]`).forEach((el) => {
      el.removeAttribute(HIDE_MARK);
      el.hidden = false;
      el.removeAttribute("hidden");
      el.removeAttribute("aria-hidden");
      el.style.removeProperty("display");
    });
  }

  function hideMenuItems(dialog, stepId) {
    const hidden = new Set(HIDDEN_MENU[stepId] || []);
    if (!hidden.size) return;
    for (const menu of deepQuery(dialog, "step-flow-menu")) {
      const items = deepQuery(
        menu,
        "ha-list-item-button, ha-md-list-item, mwc-list-item, ha-list-item"
      );
      for (const el of items) {
        const id = menuItemId(el);
        const text = (el.textContent || "").replace(/\s+/g, " ").trim();
        const byLabel =
          hidden.has("sources_done") || hidden.has("source_seq_kind_back")
            ? text === "返回" || text === "Back"
            : false;
        if (hidden.has(id) || byLabel) hideEl(el);
      }
    }
  }

  function hideGoBackFields(dialog) {
    for (const form of deepQuery(dialog, "ha-form")) {
      const schema = form.schema || form._schema;
      const rows =
        form.shadowRoot?.querySelector(".root")?.children ||
        form.shadowRoot?.children ||
        [];
      if (Array.isArray(schema)) {
        schema.forEach((item, index) => {
          if (item?.name === "go_back" && rows[index]) hideEl(rows[index]);
        });
      }
    }
    for (const el of deepQuery(
      dialog,
      "ha-formfield, ha-selector, ha-settings-row, .formfield"
    )) {
      const name =
        el.name ||
        el.getAttribute?.("name") ||
        el.getAttribute?.(".name") ||
        "";
      const text = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (
        name === "go_back" ||
        text.includes("返回上一界面") ||
        /^Go back\b/.test(text)
      ) {
        hideEl(el);
      }
    }
  }

  function isNativeCancel(el) {
    if (!el || el.hasAttribute(MARK)) return false;
    const slot = el.getAttribute?.("slot") || "";
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (text === "取消" || text === "Cancel") return true;
    return slot === "secondaryAction" && !el.hasAttribute(MARK);
  }

  function hideNativeCancel(dialog, footer) {
    const buttons = deepQuery(
      footer || dialog,
      "ha-button, mwc-button, ha-assist-chip, button"
    );
    for (const el of buttons) {
      if (isNativeCancel(el)) hideEl(el);
    }
  }

  function continueFlow(dialog, data) {
    const step = readProp(dialog, ["_step", "step"]);
    const params = readProp(dialog, ["_params", "params"]);
    if (!step || !params?.flowConfig?.handleFlowStep) return;
    dialog.dispatchEvent(
      new CustomEvent("flow-update", {
        bubbles: true,
        composed: true,
        detail: {
          stepPromise: params.flowConfig.handleFlowStep(
            dialog.hass,
            step.flow_id,
            data
          ),
        },
      })
    );
  }

  function makeButton(text, { primary, onClick }) {
    const el = document.createElement("ha-button");
    el.slot = primary ? "primaryAction" : "secondaryAction";
    el.setAttribute(MARK, primary ? "save" : "back");
    if (primary) {
      el.setAttribute("unelevated", "");
    } else {
      el.setAttribute("appearance", "plain");
    }
    el.textContent = text;
    el.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onClick();
    });
    return el;
  }

  function findFooter(dialog) {
    return (
      dialog.shadowRoot?.querySelector("ha-dialog-footer") ||
      deepQuery(dialog, "ha-dialog-footer")[0] ||
      null
    );
  }

  function findDialogShell(dialog) {
    return (
      dialog.shadowRoot?.querySelector("ha-dialog, ha-wa-dialog, ha-md-dialog") ||
      deepQuery(dialog, "ha-dialog, ha-wa-dialog, ha-md-dialog")[0] ||
      dialog.shadowRoot ||
      dialog
    );
  }

  function layoutFooter(footer, { back, save }) {
    const inner = footer.shadowRoot?.querySelector("footer") || footer;
    if (!inner?.style) return;
    inner.style.display = "flex";
    inner.style.width = "100%";
    const hasPrimary =
      save ||
      footer.querySelector('[slot="primaryAction"]') ||
      footer.querySelector(`[${MARK}="save"]`);
    if (back && hasPrimary) inner.style.justifyContent = "space-between";
    else if (back && !hasPrimary) inner.style.justifyContent = "flex-start";
    else inner.style.justifyContent = "flex-end";
  }

  function clearInjected(dialog) {
    const root = dialog.shadowRoot || dialog;
    root.querySelectorAll?.("[data-hisense-e7n-footer]").forEach((el) =>
      el.remove()
    );
    for (const footer of deepQuery(dialog, "ha-dialog-footer")) {
      footer.querySelectorAll(`[${MARK}]`).forEach((el) => el.remove());
    }
  }

  function wantsSave(step) {
    return false;
  }

  function wantsBack(step) {
    return step.step_id !== "init";
  }

  function backPayload(step) {
    if (step.type === "menu") {
      if (step.step_id === "sources") return { next_step_id: "sources_done" };
      if (step.step_id === "source_seq_kind") {
        return { next_step_id: "source_seq_kind_back" };
      }
      return { next_step_id: "back" };
    }
    return { go_back: true };
  }

  function isHisenseOptions(dialog, params, step) {
    const domain = params?.domain || step?.translation_domain;
    if (domain === DOMAIN) return true;
    if (params?.flowConfig?.flowType === "options_flow") {
      const heading = deepQuery(
        dialog,
        ".dialog-title, [slot='heading'], ha-dialog-header"
      );
      const text = heading
        .map((el) => (el.textContent || "").replace(/\s+/g, " ").trim())
        .join(" ");
      if (
        text.includes("Hisense E7N") ||
        text.includes("海信 E7N") ||
        text.includes("海信E7N")
      ) {
        return true;
      }
    }
    return false;
  }

  function injectFooter(dialog, step) {
    const text = labels(dialog.hass);
    const showSave = wantsSave(step);
    const showBack = wantsBack(step);
    if (!showSave && !showBack) return;

    let footer = findFooter(dialog);
    if (!footer && step.type === "menu") {
      footer = document.createElement("ha-dialog-footer");
      footer.setAttribute("slot", "footer");
      footer.setAttribute("data-hisense-e7n-footer", "1");
      findDialogShell(dialog).appendChild(footer);
    }
    if (!footer) return;

    hideNativeCancel(dialog, footer);
    footer.querySelectorAll(`[${MARK}]`).forEach((el) => el.remove());
    if (showBack) {
      footer.appendChild(
        makeButton(text.back, {
          primary: false,
          onClick: () => continueFlow(dialog, backPayload(step)),
        })
      );
    }
    if (showSave) {
      footer.appendChild(
        makeButton(text.save, {
          primary: true,
          onClick: () => continueFlow(dialog, {}),
        })
      );
    }
    layoutFooter(footer, { back: showBack, save: showSave });
  }

  function enhance(dialog) {
    const params = readProp(dialog, ["_params", "params"]);
    const step = readProp(dialog, ["_step", "step"]);
    if (!params || !step || dialog._loading) return;
    if (
      params.flowConfig?.flowType &&
      params.flowConfig.flowType !== "options_flow"
    ) {
      return;
    }
    if (!isHisenseOptions(dialog, params, step)) return;

    const key = `${step.flow_id}:${step.step_id}:${step.type}`;
    const marked = deepQuery(dialog, `[data-hisense-e7n-key="${key}"]`)[0];
    const hasButtons = deepQuery(dialog, `[${MARK}]`).length > 0;
    if (dialog._hisenseE7nUiKey === key && marked && hasButtons) {
      hideMenuItems(dialog, step.step_id);
      hideGoBackFields(dialog);
      return;
    }

    if (dialog._hisenseE7nUiKey !== key) {
      restoreHidden(dialog);
      clearInjected(dialog);
    }
    dialog._hisenseE7nUiKey = key;
    hideMenuItems(dialog, step.step_id);
    hideGoBackFields(dialog);
    injectFooter(dialog, step);
    deepQuery(dialog, `[${MARK}]`).forEach((el) => {
      el.setAttribute("data-hisense-e7n-key", key);
    });
    const footer = findFooter(dialog);
    if (footer) footer.setAttribute("data-hisense-e7n-key", key);
  }

  function scan() {
    deepQuery(document, DIALOG_SEL).forEach(enhance);
  }

  setInterval(scan, 300);
  const observer = new MutationObserver(scan);
  observer.observe(document.body, { childList: true, subtree: true });
  scan();
})();
