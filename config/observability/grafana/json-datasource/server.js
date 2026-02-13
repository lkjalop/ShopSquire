const express = require("express");

const app = express();
app.use(express.json());

app.get("/", (_req, res) => {
  res.json({ status: "ok", name: "shopsquire-json" });
});

app.post("/search", (_req, res) => {
  res.json(["orders", "decisions", "security"]);
});

app.post("/query", async (req, res) => {
  const baseUrl = process.env.API_BASE || "http://api:8080";
  const days = req.body?.range?.from ? 7 : 7;
  const url = `${baseUrl.replace(/\\/$/, "")}/api/v1/admin/analytics?days=${days}`;
  try {
    const fetch = global.fetch || (await import("node-fetch")).default;
    const resp = await fetch(url, { headers: { "x-api-key": process.env.API_KEY || "local-merchant-key" } });
    const data = await resp.json();
    const series = data?.series || {};
    const targets = req.body?.targets || [];
    const frameFor = (name) => {
      const points = (series[name] || []).map((p) => [p.count, Date.parse(p.day)]);
      return {
        target: name,
        datapoints: points,
      };
    };
    const frames = targets.map((t) => frameFor(t.target));
    res.json(frames);
  } catch (e) {
    res.json([]);
  }
});

app.post("/annotations", (_req, res) => {
  res.json([]);
});

const port = process.env.PORT || 3333;
app.listen(port, () => {
  console.log(`JSON datasource listening on ${port}`);
});
