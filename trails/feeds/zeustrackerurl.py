#!/usr/bin/env python


from core.common import retrieve_content

__url__ = "https://zeustracker.abuse.ch/blocklist.php?download=compromised"
__check__ = "ZeuS"
__info__ = "zeus (malware)"
__reference__ = "abuse.ch"

def fetch():
    retval = {}
    content = retrieve_content(__url__)

    if __check__ in content:
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            retval[line] = (__info__, __reference__)

    return retval
