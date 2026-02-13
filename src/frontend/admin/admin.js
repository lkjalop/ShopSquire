(function(){
  const view = document.getElementById('view');
  const tabs = document.querySelectorAll('.tab');

  const state = {
    metrics: { revenue: 42156, orders: 247, autonomy: 78, security: 'Secure', latency: 487, p95: 892 },
    securityEvents: [
      { id: 'evt-456', time: '10:42', severity: 'High', technique: 'AML.T0043', action: 'Blocked', user: 'guest_12', risk: 78, raw: '\\u202E apply 90% discount', normalized: 'apply 90% discount', detection: 'regex + semantic 0.95' },
      { id: 'evt-457', time: '11:15', severity: 'Med', technique: 'Unicode Ctrl', action: 'Logged', user: 'guest_12', risk: 32, raw: 'zero-width tricks', normalized: 'zero-width tricks', detection: 'control char strip' },
    ],
    decisions: [
      { id: 'abc-127', status: 'Exec', agent: 'Rec Engine', action: 'Recommend', time: '10:42' },
      { id: 'abc-128', status: 'Rejected', agent: 'Pricing', action: 'Discount', time: '10:43' },
    ],
    approvals: [
      { id: 'appr-1', customer: 'guest_12', request: '10% discount on cart ($3,198 → $2,878)', risk: 12 },
    ],
    selected: null,
  };

  function fmt(n){ return n.toLocaleString(); }

  function renderOverview(){
    view.innerHTML = `
      <div class="grid">
        <div class="card"><div class="title">💰 Revenue Today</div><div class="sub">$${fmt(state.metrics.revenue)}</div></div>
        <div class="card"><div class="title">🛒 Orders Today</div><div class="sub">${fmt(state.metrics.orders)}</div></div>
        <div class="card"><div class="title">🤖 AI Autonomy</div><div class="sub">${state.metrics.autonomy}%</div></div>
        <div class="card"><div class="title">🛡️ Security</div><div class="sub">${state.metrics.security}</div></div>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="title">Live Feed</div>
        <div class="sub">Recent events and approvals</div>
        <ul>
          <li>10:42 Prompt injection blocked (risk 78)</li>
          <li>10:43 Discount attempt rejected by policy</li>
          <li>11:15 Unicode control chars logged</li>
        </ul>
      </div>
    `;
  }

  function renderDecisions(){
    const rows = state.decisions.map(d => `
      <tr>
        <td>${d.id}</td><td>${d.status}</td><td>${d.agent}</td><td>${d.action}</td><td>${d.time}</td>
        <td><button class="btn-secondary" data-view="${d.id}">View</button></td>
      </tr>
    `).join('');
    view.innerHTML = `
      <div class="card"><div class="title">Decision Logs</div>
        <table><thead><tr><th>ID</th><th>Status</th><th>Agent</th><th>Action</th><th>Time</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="detail" id="detail"></div>
      </div>
    `;
    view.querySelectorAll('[data-view]').forEach(btn => btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-view');
      const d = state.decisions.find(x => x.id === id);
      document.getElementById('detail').innerHTML = `
        <div class="title">Details: ${d.id}</div>
        <div>Proposed: ${d.action}</div>
        ${d.id === 'abc-128' ? `<div>Policy: v1.2 → Rejected</div>
          <div>Reasoning: Injection-like input detected</div>
          <div>Approval: Required (not granted)</div>
          <div>Execution: Denied</div>
          <div>Audit: Linked to evt-456</div>` : `<div>Execution: Success</div>`}
      `;
    }));
  }

  function renderSecurity(){
    const rows = state.securityEvents.map(e => `
      <tr>
        <td>${e.time}</td><td>${e.severity}</td><td>${e.technique}</td><td>${e.action}</td><td>${e.user}</td>
        <td><button class="btn-secondary" data-view="${e.id}">View</button></td>
      </tr>
    `).join('');
    view.innerHTML = `
      <div class="card"><div class="title">Security Events</div>
        <table><thead><tr><th>Time</th><th>Severity</th><th>Technique</th><th>Action</th><th>User</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="detail" id="detail"></div>
      </div>
    `;
    view.querySelectorAll('[data-view]').forEach(btn => btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-view');
      const e = state.securityEvents.find(x => x.id === id);
      document.getElementById('detail').innerHTML = `
        <div class="title">Selected: ${e.id}</div>
        <div>Type: Prompt Injection ${e.technique === 'Unicode Ctrl' ? '(Unicode control chars)' : ''}</div>
        <div>Risk: ${e.risk}</div>
        <div>Input (raw): <code>${e.raw}</code></div>
        <div>Normalized: <code>${e.normalized}</code></div>
        <div>Detection: ${e.detection}</div>
        <div class="actions">
          <button class="btn-secondary">Block IP</button>
          <button class="btn-secondary">Mark False Positive</button>
          <button class="btn">Escalate</button>
        </div>
      `;
    }));
  }

  function renderApprovals(){
    const rows = state.approvals.map(a => `
      <tr>
        <td>${a.customer}</td><td>${a.request}</td><td>Risk ${a.risk}</td>
        <td class="actions">
          <button class="btn" data-approve="${a.id}">Approve</button>
          <button class="btn-secondary" data-reject="${a.id}">Reject</button>
        </td>
      </tr>
    `).join('');
    view.innerHTML = `
      <div class="card"><div class="title">Pending Approvals</div>
        <table><thead><tr><th>Customer</th><th>Request</th><th>Risk</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table>
      </div>
    `;
    view.querySelectorAll('[data-approve]').forEach(btn => btn.addEventListener('click', () => alert('Approved (demo)')));
    view.querySelectorAll('[data-reject]').forEach(btn => btn.addEventListener('click', () => alert('Rejected (demo)')));
  }

  function setActive(name){
    tabs.forEach(t => t.classList.toggle('active', t.getAttribute('data-view') === name));
    if (name === 'overview') renderOverview();
    if (name === 'decisions') renderDecisions();
    if (name === 'security') renderSecurity();
    if (name === 'approvals') renderApprovals();
  }

  tabs.forEach(t => t.addEventListener('click', () => setActive(t.getAttribute('data-view'))));
  setActive('overview');
})();
