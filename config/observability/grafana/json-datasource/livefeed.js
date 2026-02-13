const express = require("express");

const app = express();
app.use(express.json());

app.get("/", (_req, res) => {
  res.json({ status: "ok", name: "shopsquire-live-feed" });
});

app.post("/search", (_req, res) => {
  res.json(["compliance_live_feed"]);
});

app.post("/query", async (_req, res) => {
  const baseUrl = process.env.API_BASE || "http://api:8080";
  const url = `${baseUrl.replace(/\\/$/, "")}/api/v1/admin/compliance/live-feed?limit=50`;
  try {
    const fetch = global.fetch || (await import("node-fetch")).default;
    const resp = await fetch(url, { headers: { "x-api-key": process.env.API_KEY || "local-owner-key" } });
    const data = await resp.json();
    const items = data.items || [];
    const table = {
      columns: [
        { text: "time", type: "time" },
        { text: "type", type: "string" },
        { text: "summary", type: "string" },
        { text: "tags", type: "string" },
        { text: "controls", type: "string" },
      ],
      rows: items.map((i) => [
        Date.parse(i.time || new Date().toISOString()),
        i.type,
        i.summary,
        JSON.stringify(i.tags || {}),
        (i.controls || []).join(", "),
      ]),
      type: "table",
    };
    res.json([table]);
  } catch (e) {
    res.json([]);
  }
});

app.post("/annotations", (_req, res) => {
  res.json([]);
});

const port = process.env.PORT || 3334;
app.listen(port, () => {
  console.log(`Live feed JSON datasource listening on ${port}`);
});
