#!/usr/bin/env python


from core.common import retrieve_content

__url__ = "https://isc.sans.edu/feeds/suspiciousdomains_High.txt"
__check__ = "DShield.org"
__info__ = "domain (suspicious)"
__reference__ = "dshield.org"

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
