document.addEventListener('DOMContentLoaded', function () {
  const traceInput = document.getElementById('traceId');
  const apiKeyInput = document.getElementById('apiKey');
  const fetchBtn = document.getElementById('fetchBtn');
  const sampleBtn = document.getElementById('sampleBtn');
  const resultEl = document.getElementById('result');
  const summaryGrid = document.getElementById('summaryGrid');
  const ctx = document.getElementById('chart').getContext('2d');

  let chart = null;
  let timelineChart = null;
  let stackedChart = null;

  function renderSummary(data) {
    resultEl.textContent = JSON.stringify(data, null, 2);
    const s = data.summary || data;
    summaryGrid.innerHTML = '';
    const fields = ['trace_id','tier','tool_budget_remaining','interleaving_iterations','agent_invocations','agent_latency_ms_total'];
    for (const f of fields) {
      const v = s[f] === undefined ? '-' : s[f];
      const d = document.createElement('div');
      d.textContent = f + ': ' + JSON.stringify(v);
      summaryGrid.appendChild(d);
    }

    // Chart: two bars — invocations and latency
    const labels = ['agent_invocations', 'agent_latency_ms_total'];
    const values = [s.agent_invocations || 0, s.agent_latency_ms_total || 0];
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{ label: 'Counts / ms', data: values, backgroundColor: ['#3b82f6','#ef4444'] }]
      },
      options: { responsive: true, scales: { y: { beginAtZero: true } } }
    });
  }

  async function fetchSummary(traceId, key) {
    if (!traceId) {
      alert('enter a trace id');
      return;
    }
    const url = `/api/v1/admin/interleaving/${encodeURIComponent(traceId)}/summary`;
    try {
      const resp = await fetch(url, { headers: { 'x-api-key': key || '' } });
      if (!resp.ok) {
        const txt = await resp.text();
        resultEl.textContent = `Error ${resp.status}: ${txt}`;
        return;
      }
      const data = await resp.json();
      renderSummary(data);
      // Also fetch per-bucket timeline
      fetchByTime(traceId, key);
    } catch (err) {
      resultEl.textContent = 'Fetch failed: ' + String(err);
    }
  }

  async function fetchByTime(traceId, key, bucketSeconds = 1) {
    const url = `/api/v1/trace/${encodeURIComponent(traceId)}/summary/by_time?bucket_seconds=${bucketSeconds}`;
    try {
      const resp = await fetch(url, { headers: { 'x-api-key': key || '' } });
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      renderTimeline(data);
    } catch (err) {
      // ignore timeline errors
    }
  }

  function renderTimeline(data) {
    const buckets = (data && data.buckets) || [];
    const labels = buckets.map(b => b.bucket);
    const agentCounts = buckets.map(b => b.agent_count || 0);
    const latencies = buckets.map(b => b.latency_ms_total || 0);
    // Destroy the bar summary chart before reusing the canvas — Chart.js throws if canvas is in use
    if (chart) { chart.destroy(); chart = null; }
    if (timelineChart) timelineChart.destroy();
    const ctx2 = document.getElementById('chart').getContext('2d');
    timelineChart = new Chart(ctx2, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Agent Count', data: agentCounts, borderColor: '#3b82f6', yAxisID: 'y1', fill: false },
          { label: 'Latency (ms)', data: latencies, borderColor: '#ef4444', yAxisID: 'y2', fill: false }
        ]
      },
      options: {
        responsive: true,
        scales: {
          y1: { type: 'linear', position: 'left', beginAtZero: true },
          y2: { type: 'linear', position: 'right', beginAtZero: true, grid: { drawOnChartArea: false } }
        }
      }
    });

    // render stacked per-agent bars
    renderStackedBars(buckets, labels);
    // render tags heatmap
    renderTagsHeatmap(buckets, labels);
  }

  function renderStackedBars(buckets, labels) {
    // collect all agent names
    const agentSet = new Set();
    buckets.forEach(b => {
      (b.agents_invoked || []).forEach(a => agentSet.add(a));
    });
    const agents = Array.from(agentSet).slice(0, 10); // cap to top 10 agents
    const datasets = agents.map((agent, idx) => ({
      label: agent,
      data: buckets.map(b => (b.agents_invoked && b.agents_invoked.includes(agent)) ? 1 : 0),
      backgroundColor: `hsl(${(idx * 47) % 360} 70% 50% / 0.85)`,
      stack: 'agents'
    }));

    const sc = document.getElementById('stackedChart');
    if (!sc) return;
    const ctxs = sc.getContext('2d');
    if (stackedChart) stackedChart.destroy();
    stackedChart = new Chart(ctxs, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => items[0].label,
              label: (ctx) => {
                const bucketIdx = ctx.dataIndex;
                const agent = ctx.dataset.label;
                const count = ctx.parsed.y || ctx.raw;
                const latency = (buckets[bucketIdx] && buckets[bucketIdx].latency_ms_total) || 0;
                return `${agent}: ${count} calls — ${latency} ms total`;
              }
            }
          }
        },
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } }
      }
    });
  }

  function renderTagsHeatmap(buckets, labels) {
    const canvas = document.getElementById('heatmap');
    const legend = document.getElementById('heatmapLegend');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    // top tags across all buckets
    const tagCounts = {};
    buckets.forEach(b => {
      (b.tags || []).forEach(t => { tagCounts[t] = (tagCounts[t] || 0) + 1; });
    });
    const topTags = Object.keys(tagCounts).sort((a,b) => tagCounts[b]-tagCounts[a]).slice(0, 8);
    const cols = Math.max(1, buckets.length);
    const rows = topTags.length || 1;
    // clear
    ctx.clearRect(0,0,canvas.width,canvas.height);
    const cellW = Math.floor(canvas.width / cols);
    const cellH = Math.floor(canvas.height / rows);
    // compute max count for normalization
    let maxC = 0;
    for (let r=0;r<rows;r++){
      for (let c=0;c<cols;c++){
        const tag = topTags[r];
        const bucket = buckets[c] || {};
        const present = (bucket.tags || []).includes(tag) ? 1 : 0;
        if (present > maxC) maxC = present;
      }
    }
    if (maxC === 0) maxC = 1;
    // draw grid
    for (let r=0;r<rows;r++){
      for (let c=0;c<cols;c++){
        const tag = topTags[r];
        const bucket = buckets[c] || {};
        const count = (bucket.tags || []).includes(tag) ? 1 : 0;
        const intensity = count / maxC;
        const color = `rgba(59,130,246,${0.15 + 0.85*intensity})`;
        ctx.fillStyle = color;
        ctx.fillRect(c*cellW, r*cellH, cellW-1, cellH-1);
      }
    }
    // labels on left
    ctx.fillStyle = '#222';
    ctx.font = '12px Arial';
    for (let r=0;r<rows;r++){
      ctx.fillText(topTags[r], 4, r*cellH + 12);
    }
    // render legend
    if (legend) {
      legend.innerHTML = `<div>Top tags: ${topTags.join(', ')}</div>`;
    }
  }

  fetchBtn.addEventListener('click', function () {
    fetchSummary(traceInput.value.trim(), apiKeyInput.value.trim());
  });

  sampleBtn.addEventListener('click', function () {
    // demo defaults
    traceInput.value = 'demo-trace-1';
    apiKeyInput.value = 'local-developer-key';
    fetchSummary('demo-trace-1', 'local-developer-key');
  });
});
