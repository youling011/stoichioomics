"""Linux zombies have exited even while a Popen handle retains their PID."""
import os,sys
from functools import lru_cache
from pathlib import Path

def linux_process_has_exited(pid):
    if not sys.platform.startswith('linux'):return False
    try:
        state=(Path('/proc')/str(int(pid))/'stat').read_text().rsplit(')',1)[1].split()[0]
    except (OSError,ValueError,IndexError):
        return False  # Let the existing kill(pid, 0) checks handle absence/permissions.
    return state in {'Z','X'}

@lru_cache(maxsize=1)
def _boot_epoch():
    return int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))

def linux_pid_matches_record(pid,recorded_at):
    """Reject a PID reused after the persisted consumer/lock record was written."""
    if not sys.platform.startswith('linux'):return True
    try:
        fields=(Path('/proc')/str(int(pid))/'stat').read_text().rsplit(')',1)[1].split()
        started=_boot_epoch()+int(fields[19])/os.sysconf('SC_CLK_TCK')
        return started<=float(recorded_at)+1.0  # btime is rounded to whole seconds.
    except (OSError,ValueError,IndexError,StopIteration):return True
