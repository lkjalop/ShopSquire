import os, sys
print('CWD:', os.getcwd())
print('PATH0:', sys.path[0])
print('PATH1:', sys.path[1] if len(sys.path) > 1 else None)
print('PATH2:', sys.path[2] if len(sys.path) > 2 else None)
import src.app.analytics.anomaly
print('IMPORT_OK')
