const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "panel.spec.cjs",
  workers: 1,
  retries: 0,
  timeout: 30000,
  use: { headless: true, viewport: { width: 390, height: 844 } },
});
