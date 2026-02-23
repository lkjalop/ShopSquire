import React from 'react';

export class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: String((error && error.message) || 'unknown_error'),
    };
  }

  componentDidCatch(error, info) {
    try {
      console.error('storefront_app_error_boundary', { error, info });
    } catch {}
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }} role="alert" aria-live="assertive">
          <h2 style={{ marginTop: 0 }}>Storefront Error</h2>
          <p>The page encountered an unexpected error.</p>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#7f1d1d' }}>{this.state.message}</pre>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

