class SecretAskPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  connectedCallback() {
    this.render();
  }

  render() {
    if (!this._hass) return;
    const rows = this._hass.states["sensor.secret_ask"]?.attributes.requests || [];
    const selected = new URLSearchParams(window.location.search).get("request");
    const shown = selected ? rows.filter(row => row.id === selected) : rows.filter(row => row.state === "pending");
    if (!this.cards) {
      this.cards = new Map();
      this.text("h1", "Secret approvals");
      this.empty = this.text("p", "");
    }
    this.style.cssText = "display:block;max-width:52rem;margin:auto;padding:1.5rem;box-sizing:border-box";
    this.empty.textContent = shown.length ? "" : selected ? "This request is unavailable or no longer pending. Nothing here can approve another request." : "No pending requests.";
    for (const [id, card] of this.cards) {
      if (!shown.some(row => row.id === id)) {
        card.node.remove();
        this.cards.delete(id);
      }
    }
    for (const row of shown) {
      const signature = JSON.stringify(row);
      const previous = this.cards.get(row.id);
      if (previous?.signature === signature) continue;
      const node = this.request(row);
      if (previous) previous.node.replaceWith(node);
      else this.append(node);
      this.cards.set(row.id, { signature, node });
    }
  }

  text(tag, value, parent = this) {
    const element = document.createElement(tag);
    element.textContent = value;
    parent.append(element);
    return element;
  }

  request(row) {
    const section = document.createElement("section");
    section.style.cssText = "border:1px solid var(--divider-color);padding:1rem;margin-bottom:1rem;border-radius:.5rem";
    this.text("h2", row.session || row.id, section);
    this.text("p", `Request ${row.id}: ${row.state}`, section);
    if (row.state !== "pending") return section;
    const references = Object.entries(row.env || {}).map(([name, value]) => `${name}=${value}`);
    for (const [label, value] of [["Exact command arguments", JSON.stringify(row.argv)],
      ["References", references.join("\n")], ["Why", row.reason || "no reason given"],
      ["Directory", row.cwd], ["Host", row.host], ["Session", row.session],
      ["Expires", new Date(row.expires * 1000).toLocaleString()]]) {
      this.text("strong", label, section);
      const text = this.text("pre", value, section);
      text.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;font:inherit";
    }
    const status = this.text("p", "", section);
    for (const [label, action] of [["Approve", row.approve], ["Deny", row.deny]]) {
      const button = this.text("button", label, section);
      button.type = "button";
      button.style.cssText = "font:inherit;padding:.7rem 1.4rem;margin-right:.7rem;cursor:pointer";
      button.onclick = async () => {
        section.querySelectorAll("button").forEach(item => { item.disabled = true; });
        try {
          await this._hass.callService("script", "secret_ask_decide", { action });
          status.textContent = "Decision sent. Waiting for the broker result.";
        } catch {
          status.textContent = "Could not send this decision. Reopen this same request to check its status.";
        }
      };
    }
    return section;
  }
}
customElements.define("secret-ask-panel", SecretAskPanel);
