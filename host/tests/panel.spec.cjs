const { test, expect } = require("@playwright/test");
const http = require("node:http");
const path = require("node:path");

let server;
let origin;
test.beforeAll(async () => {
  server = http.createServer((request, response) => {
    response.end("<!doctype html><html><body></body></html>");
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => new Promise(resolve => server.close(resolve)));

async function pending(page) {
  await page.goto(`${origin}/secret-approval?request=second`);
  await page.addScriptTag({ path: path.resolve(__dirname, "../home-assistant/config/www/secret-approval.js") });
  await page.evaluate(() => {
    window.calls = [];
    window.rows = [
      { id: "first", token: "token-one", title: "Secret approval: one", message: "Why: first" },
      { id: "second", token: "token-two", title: "<b>Secret approval: two</b>",
        message: "Why: <img src=x onerror=alert(1)>\nCommand: true" },
    ];
    window.hass = { callWS: async message => {
      calls.push(message);
      if (message.type === "secret_approval/open") return rows.map(row => ({ ...row }));
      rows = rows.filter(row => row.id !== message.request);
    } };
    window.panel = document.createElement("secret-approval-panel");
    document.body.append(panel);
    panel.hass = hass;
  });
  await expect(page.locator("section")).toHaveCount(2);
}

for (const [action, decision] of [["Approve", "approved"], ["Deny", "denied"]]) {
  test(`${action} stays bound through refresh and renders request text safely`, async ({ page }) => {
    await pending(page);
    await expect(page.locator("img, b")).toHaveCount(0);
    await expect(page.locator("section h2").first()).toHaveText("<b>Secret approval: two</b>");
    await expect(page.locator("section pre").first()).toHaveText("Why: <img src=x onerror=alert(1)>\nCommand: true");
    const button = page.locator("section").first().getByRole("button", { name: action, exact: true });
    const box = await button.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.evaluate(() => panel.load());
    await page.mouse.up();
    await expect(page.locator("section")).toHaveCount(1);
    expect(await page.evaluate(() => calls.filter(call => call.type === "secret_approval/decide"))).toEqual([
      { type: "secret_approval/decide", request: "second", token: "token-two", decision },
    ]);
    await expect(page.getByText(/The request you opened is decided or expired/)).toBeVisible();
  });
}

test("failed and stale decisions stay explicit and unauthorized reads hide requests", async ({ page }) => {
  await pending(page);
  await page.evaluate(() => {
    hass.callWS = async message => {
      calls.push(message);
      if (message.type === "secret_approval/open") return rows.map(row => ({ ...row }));
      throw new Error("The request is decided or expired");
    };
  });
  await page.locator("section").first().getByRole("button", { name: "Deny", exact: true }).click();
  await expect(page.getByText("Not recorded: The request is decided or expired", { exact: true })).toBeVisible();
  await expect(page.locator("section").first().getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  await page.evaluate(() => { rows = [{ ...rows[0], token: "new-token", message: "Why: asked again" }]; return panel.load(); });
  await expect(page.locator("section pre")).toHaveText("Why: asked again");
  await page.evaluate(() => { rows = []; return panel.load(); });
  await expect(page.getByText(/No request waits/)).toBeVisible();
  await page.evaluate(() => {
    hass.callWS = async () => { throw new Error("Only the operator decides secret approvals"); };
    return panel.load();
  });
  await expect(page.getByText(/not available: Only the operator decides/)).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});
