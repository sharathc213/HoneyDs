#!/usr/bin/env python


from core.common import retrieve_content

__url__ = "https://www.cruzit.com/xxwbl2txt.php"
__check__ = "ipaddress"
__info__ = "known attacker"
__reference__ = "cruzit.com"

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
