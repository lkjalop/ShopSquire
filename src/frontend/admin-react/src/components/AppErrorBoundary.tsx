import React from 'react';

type State = {
  hasError: boolean;
  message: string;
};

export class AppErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  constructor(props: React.PropsWithChildren) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: String(error?.message || 'unknown_error'),
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    try {
      console.error('admin_app_error_boundary', { error, info });
    } catch {}
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }} role="alert" aria-live="assertive">
          <h2 style={{ marginTop: 0 }}>Admin UI Error</h2>
          <p>The interface hit an unexpected error and stopped rendering.</p>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#7f1d1d' }}>{this.state.message}</pre>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

