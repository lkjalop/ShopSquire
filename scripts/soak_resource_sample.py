"""Local diagnostic snapshots, without command lines, tokens or message content."""
from collections import Counter
from datetime import datetime, timezone
import os


def snapshot(*, browser_parent=None, ports=(8087, 5177)):
    import psutil
    result = {'at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    memory = psutil.virtual_memory()
    result['memory_available_bytes'] = memory.available
    result['memory_percent'] = memory.percent
    result['system_process_count'] = len(psutil.pids())
    # Distinguish host contention from growth in the application under test.
    # Only process identity and RSS are recorded; no arguments or environment.
    host_processes = []
    for process in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            info = process.info
            if info['memory_info'] is not None:
                host_processes.append({'pid': info['pid'], 'name': info['name'],
                                       'rss_bytes': info['memory_info'].rss})
        except (psutil.Error, OSError):
            continue
    result['largest_host_processes'] = sorted(host_processes, key=lambda row: row['rss_bytes'], reverse=True)[:10]
    owners = {os.getpid()}
    if browser_parent:
        owners.add(browser_parent)
    try:
        connections = psutil.net_connections(kind='tcp')
        result['tcp_states'] = dict(Counter(c.status for c in connections))
        owners.update(c.pid for c in connections if c.pid and c.status == psutil.CONN_LISTEN
                      and c.laddr.port in ports)
    except (psutil.Error, OSError) as exc:
        result['errors'].append(type(exc).__name__ + ':tcp')
    processes = {}
    for pid in sorted(owners):
        try:
            root = psutil.Process(pid)
            for process in [root, *root.children(recursive=True)]:
                try:
                    with process.oneshot():
                        processes[process.pid] = {'pid': process.pid, 'name': process.name(),
                            'started_at': process.create_time(), 'rss_bytes': process.memory_info().rss,
                            'threads': process.num_threads(),
                            'handles': process.num_handles() if os.name == 'nt' else process.num_fds()}
                except (psutil.Error, OSError):
                    continue
        except (psutil.Error, OSError):
            continue
    result['application_processes'] = list(processes.values())
    return result
