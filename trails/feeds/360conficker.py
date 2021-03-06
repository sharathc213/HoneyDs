#!/usr/bin/env python

 

import re

from core.common import retrieve_content

__url__ = "https://data.netlab.360.com/feeds/dga/conficker.txt"
__check__ = "netlab 360"
__info__ = "conficker dga (malware)"
__reference__ = "360.com"

def fetch():
    retval = {}
    content = retrieve_content(__url__)

    if __check__ in content:
        for match in re.finditer(r"(?m)^([\w.]+)\s+2\d{3}\-", content):
            retval[match.group(1)] = (__info__, __reference__)

    return retval
