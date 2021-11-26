#!/usr/bin/env python


from core.common import retrieve_content

__url__ = "https://raw.githubusercontent.com/Hestat/minerchk/master/hostslist.txt"
__check__ = ".com"
__info__ = "crypto mining (suspicious)"
__reference__ = "github.com/Hestat"

def fetch():
    retval = {}
    content = retrieve_content(__url__)

    if __check__ in content:
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or '.' not in line:
                continue
            retval[line] = (__info__, __reference__)

    return retval
