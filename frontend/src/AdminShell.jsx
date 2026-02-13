import React from 'react'

export default function AdminShell() {
  return (
    <div style={{fontFamily: 'Inter, system-ui, Arial'}}>
      <h1>ShopSquire Admin</h1>
      <p>Admin analytics and Grafana embeds will appear here.</p>
      <div style={{display: 'flex', gap: 12}}>
        <iframe title="grafana" src="/admin/grafana_proxy/api/dashboards/uid/shopsquire-geo" style={{width: 800, height: 600, border: '1px solid #ddd'}}/>
        <div>
          <h2>Quick Links</h2>
          <ul>
            <li><a href="/api/v1/analytics/ragas/summary">RAGAS Summary</a></li>
            <li><a href="/api/v1/analytics/query_clusters/latest">Latest Clusters</a></li>
            <li><a href="/metrics">Metrics</a></li>
          </ul>
        </div>
      </div>
    </div>
  )
}
