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
  await page.goto(`${origin}/secret-ask?request=first`);
  await page.addScriptTag({ path: path.resolve(__dirname, "../home-assistant/config/www/secret-ask.js") });
  await page.evaluate(() => {
    window.calls = [];
    const first = { id: "first", state: "pending", env: { DEMO: "op://Example/Demo/password" },
      reason: "<img src=x onerror=alert(1)>", argv: ["/usr/bin/true"], cwd: "/",
      host: "test-host", session: "test-session", expires: Date.now() / 1000 + 600,
      approve: "approve-first", deny: "deny-first" };
    window.rows = [first, { ...first, id: "newer", approve: "approve-newer", deny: "deny-newer" }];
    window.hass = { states: { "sensor.secret_ask": { attributes: { requests: rows } } },
      callService: async (...args) => { calls.push(args); } };
    window.panel = document.createElement("secret-ask-panel");
    document.body.append(panel);
    panel.hass = hass;
  });
}

for (const action of ["Approve", "Deny"]) {
  test(`${action} stays bound through unrelated updates and renders request text safely`, async ({ page }) => {
    await pending(page);
    await expect(page.locator("img")).toHaveCount(0);
    await expect(page.getByText("<img src=x onerror=alert(1)>", { exact: true })).toHaveCount(1);
    await expect(page.getByText("DEMO=op://Example/Demo/password", { exact: true })).toHaveCount(1);
    const button = page.getByRole("button", { name: action, exact: true });
    const box = await button.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.evaluate(() => { hass.states.unrelated = { state: "changed" }; panel.hass = hass; });
    await page.evaluate(() => { rows[1].reason = "another request changed"; panel.hass = hass; });
    await page.mouse.up();
    await page.waitForFunction(() => calls.length === 1);
    await page.evaluate(() => { hass.states.unrelated = { state: "again" }; panel.hass = hass; });
    await expect(button).toBeDisabled();
    expect(await page.evaluate(() => calls)).toEqual([
      ["script", "secret_ask_decide", { action: `${action.toLowerCase()}-first` }],
    ]);
    await page.evaluate(() => { hass.states["sensor.secret_ask"].attributes.requests = [rows[1]]; panel.hass = hass; });
    await expect(page.getByRole("button")).toHaveCount(0);
    await expect(page.getByText(/no longer pending/)).toBeVisible();
  });
}
