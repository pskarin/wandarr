__version__ = '1.0.5'
__author__ = 'Marshall L Smith Jr <marshallsmithjr@gmail.com>'
__license__ = 'GPLv3'


#
# Global state indicators
#
from queue import Queue

SSH: str = "/usr/bin/ssh"
VERBOSE = False
DRY_RUN = False
SHOW_INFO = False
DO_PING = False
SKIP_EXISTING = True
OUTPUT_FOLDER = None
OVERWRITE_SOURCE = False
console = None

status_queue = Queue()
