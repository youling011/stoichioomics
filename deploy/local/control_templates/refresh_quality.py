import sys
from pathlib import Path
sys.path.insert(0,'/control/continuation_20261025')
from quality_config import configure
print(configure(Path('/opt/local/project'),Path('/opt/local/config')))
