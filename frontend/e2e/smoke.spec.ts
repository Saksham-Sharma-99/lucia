import { expect, test, type Page } from "@playwright/test";

const run = Date.now().toString(36);
const handle = `e2e-${run}`;
const firmName = `E2E Firm ${run}`;
const username = process.env.E2E_USERNAME ?? "saksham";

async function pick(page: Page, trigger: ReturnType<Page["getByRole"]>, option: string | RegExp) {
  await trigger.click();
  await page.getByRole("option", { name: option }).click();
}

async function signIn(page: Page) {
  await page.goto("/agents");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(process.env.E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
}

/** Start from @records, give it `h`, pick allowed models, and stop on Review. */
async function fillFromTemplate(page: Page, h: string) {
  await page.goto("/agents/new?template=records");
  await page.getByLabel("Handle").fill(h);
  await page.getByLabel("Name").fill(`E2E records ${run}`);
  await page.getByRole("button", { name: "Next" }).click(); // capabilities
  await page.getByRole("button", { name: "Next" }).click(); // prompt and models
  // The template's models may not be allowed here; take the first allowed one for each role.
  for (let i = 0; i < 3; i++) {
    await page.getByRole("combobox").nth(i).click();
    await page.getByRole("option").first().click();
  }
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Next" }).click(); // policies, schedules, review
}

test.describe("signed out", () => {
  test("a wrong password is refused with a clear message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toHaveText("Username or password is incorrect.");
  });
});

test.describe("builder flows", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(({ page }) => signIn(page));

  test("create an agent from the @records template", async ({ page }) => {
    await fillFromTemplate(page, handle);
    await expect(page.getByText("The server accepts this config.")).toBeVisible();
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByRole("heading", { name: `@${handle}` })).toBeVisible();
    await expect(page.getByText(/Started from the @records template/)).toBeVisible();
  });

  test("a taken handle is caught by the server and sent back to Basic info", async ({ page }) => {
    await fillFromTemplate(page, handle);
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByText(`Handle @${handle} is taken`)).toBeVisible();
    await expect(page.getByLabel("Handle")).toBeVisible();
  });

  test("amend saves v2 and shows the diff", async ({ page }) => {
    await page.goto(`/agents/${handle}/amend?from=1`);
    await page.getByRole("tab", { name: "Prompt and models" }).click();
    await page
      .getByLabel("System prompt")
      .fill("Chase records politely. Call before the second email.");
    await expect(page.getByLabel("changed", { exact: true })).toBeVisible();
    await page.getByLabel("What changed").fill("Shorter prompt");
    await page.getByRole("button", { name: "Save as v2" }).click();
    await expect(page.getByRole("combobox").first()).toHaveText(/v2 · active/);
    await page.getByRole("tab", { name: "Versions" }).click();
    await page.getByRole("button", { name: "Show changes" }).click();
    await expect(page.getByRole("heading", { name: "Prompt" })).toBeVisible();
    await expect(page.getByText("/system_prompt")).toBeVisible();
  });

  test("a new firm gets an inactive orchestrator mapping", async ({ page }) => {
    await page.goto("/firms");
    await page.getByRole("button", { name: "New firm" }).first().click();
    await page.getByLabel("Name").fill(firmName);
    await expect(page.getByLabel("Slug")).toHaveValue(`e2e-firm-${run}`);
    await page.getByRole("button", { name: "Add firm" }).click();
    await expect(page.getByRole("heading", { name: firmName })).toBeVisible();
    await page.goto("/firm-mappings");
    await pick(page, page.getByRole("combobox", { name: "Firm" }), firmName);
    const row = page.getByRole("row", { name: /@orchestrator/ });
    await expect(row.getByText("inactive")).toBeVisible();
    await row.getByRole("link", { name: "@orchestrator" }).click();
    await page.getByRole("tab", { name: "Policies and guardrails" }).click();
    await expect(page.getByRole("heading", { name: "Alert routing" })).toBeVisible();
  });

  test("map the agent to the firm, then archiving turns the mapping off", async ({ page }) => {
    await page.goto("/firm-mappings");
    await pick(page, page.getByRole("combobox", { name: "Firm" }), firmName);
    await page.getByRole("button", { name: "Map an agent" }).first().click();
    const dialog = page.getByRole("dialog");
    await pick(page, dialog.getByRole("combobox", { name: "Agent" }), new RegExp(`@${handle}`));
    await expect(dialog.getByText("Pick a gmail connection")).toBeVisible();
    await dialog.getByRole("button", { name: "Map agent" }).click();
    const row = page.getByRole("row", { name: new RegExp(`@${handle}`) });
    await expect(row).toBeVisible();

    await page.goto(`/agents/${handle}`);
    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("menuitem", { name: "Archive" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Archive" }).click();
    await expect(page.getByText("archived").first()).toBeVisible();
    await page.goto("/firm-mappings");
    await pick(page, page.getByRole("combobox", { name: "Firm" }), firmName);
    await expect(row.getByText("inactive")).toBeVisible();
  });
});
