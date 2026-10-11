// The operator's page for waiting secret approval questions. A tap on a question's notification opens it.
// Question text comes from the requester, so it reaches the page only as text, never as markup.
class SecretApprovalPanel extends HTMLElement {
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this.load();
  }

  connectedCallback() {
    this.style.cssText = "display:block;max-width:52rem;margin:auto;padding:1.5rem;box-sizing:border-box";
    this.timer = setInterval(() => this.load(), 3000);
  }

  disconnectedCallback() {
    clearInterval(this.timer);
  }

  async load() {
    if (!this._hass) return;
    try {
      this.show(await this._hass.callWS({ type: "secret_approval/open" }));
    } catch (error) {
      this.shown = null;
      this.replaceChildren(this.text("p", "Secret approvals are not available: " + error.message));
    }
  }

  show(rows) {
    // An unchanged list keeps its buttons, so a refresh never swallows a press. A token names one sent text.
    const shown = rows.map(row => row.token).join();
    if (shown === this.shown) return;
    this.shown = shown;
    const opened = new URLSearchParams(window.location.search).get("request");
    const gone = opened && !rows.some(row => row.id === opened) ? "The request you opened is decided or expired. " : "";
    rows.sort((a, b) => (b.id === opened) - (a.id === opened));
    const note = this.text("p", gone + (rows.length ? "" : "No request waits."));
    this.replaceChildren(this.text("h1", "Secret approvals"), note, ...rows.map(row => this.card(row)));
  }

  card(row) {
    const card = document.createElement("section");
    card.style.cssText = "border:1px solid var(--divider-color);padding:1rem;margin-bottom:1rem;border-radius:.5rem";
    const message = this.text("pre", row.message);
    message.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;font:inherit";
    card.append(this.text("h2", row.title), message);
    for (const [label, decision] of [["Approve", "approved"], ["Deny", "denied"]]) {
      const button = this.text("button", label);
      button.type = "button";
      button.style.cssText = "font:inherit;padding:.7rem 1.4rem;margin-right:.7rem;cursor:pointer";
      button.onclick = () => this.decide(card, { request: row.id, token: row.token, decision });
      card.append(button);
    }
    return card;
  }

  async decide(card, decision) {
    const buttons = card.querySelectorAll("button");
    buttons.forEach(button => { button.disabled = true; });
    try {
      await this._hass.callWS({ type: "secret_approval/decide", ...decision });
    } catch (error) {
      card.append(this.text("p", "Not recorded: " + error.message));
      buttons.forEach(button => { button.disabled = false; });
    }
    this.load();
  }

  text(tag, value) {
    const element = document.createElement(tag);
    element.textContent = value;
    return element;
  }
}

customElements.define("secret-approval-panel", SecretApprovalPanel);
