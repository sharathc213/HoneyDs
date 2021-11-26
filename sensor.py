#!/usr/bin/env python


from __future__ import print_function  # Requires: Python >= 2.6
from thirdparty.six.moves import urllib as _urllib
from thirdparty import six
from core.update import update_trails
from core.update import update_ipcat
from core.settings import WHITELIST_UA_REGEX
from core.settings import WHITELIST_HTTP_REQUEST_PATHS
from core.settings import WHITELIST_LONG_DOMAIN_NAME_KEYWORDS
from core.settings import WHITELIST_DIRECT_DOWNLOAD_KEYWORDS
from core.settings import WHITELIST
from core.settings import WEB_SHELLS
from core.settings import VERSION
from core.settings import trails
from core.settings import VALID_DNS_NAME_REGEX
from core.settings import SUSPICIOUS_UA_REGEX
from core.settings import SUSPICIOUS_PROXY_PROBE_PRE_CONDITION
from core.settings import SUSPICIOUS_HTTP_REQUEST_FORCE_ENCODE_CHARS
from core.settings import SUSPICIOUS_HTTP_REQUEST_REGEXES
from core.settings import SUSPICIOUS_HTTP_REQUEST_PRE_CONDITION
from core.settings import SUSPICIOUS_HTTP_PATH_REGEXES
from core.settings import SUSPICIOUS_DOMAIN_LENGTH_THRESHOLD
from core.settings import SUSPICIOUS_DOMAIN_ENTROPY_THRESHOLD
from core.settings import SUSPICIOUS_DOMAIN_CONSONANT_THRESHOLD
from core.settings import SUSPICIOUS_DIRECT_IP_URL_REGEX
from core.settings import SUSPICIOUS_DIRECT_DOWNLOAD_EXTENSIONS
from core.settings import SUSPICIOUS_CONTENT_TYPES
from core.settings import SNAP_LEN
from core.settings import REGULAR_SENSOR_SLEEP_TIME
from core.settings import read_config
from core.settings import POTENTIAL_INFECTION_PORTS
from core.settings import PORT_SCANNING_THRESHOLD
from core.settings import INFECTION_SCANNING_THRESHOLD
from core.settings import NO_SUCH_NAME_PER_HOUR_THRESHOLD
from core.settings import NO_SUCH_NAME_COUNTERS
from core.settings import NAME
from core.settings import MAX_RESULT_CACHE_ENTRIES
from core.settings import MMAP_ZFILL_CHUNK_LENGTH
from core.settings import LOCAL_SUBDOMAIN_LOOKUPS
from core.settings import LOCALHOST_IP
from core.settings import IS_WIN
from core.settings import IPPROTO_LUT
from core.settings import IGNORE_DNS_QUERY_SUFFIXES
from core.settings import HTTP_TIME_FORMAT
from core.settings import GENERIC_SINKHOLE_REGEX
from core.settings import DNS_EXHAUSTION_THRESHOLD
from core.settings import DLT_OFFSETS
from core.settings import DAILY_SECS
from core.settings import CONSONANTS
from core.settings import CONFIG_FILE
from core.settings import CHECK_CONNECTION_MAX_RETRIES
from core.settings import CAPTURE_TIMEOUT
from core.settings import config
from core.settings import check_memory
from core.parallel import write_block
from core.parallel import worker
from core.log import log_event
from core.log import log_error
from core.log import get_error_log_handle
from core.log import flush_condensed_events
from core.log import create_log_directory
from core.enums import TRAIL
from core.enums import PROTO
from core.enums import CACHE_TYPE
from core.enums import BLOCK_MARKER
from core.datatype import LRUDict
from core.compat import xrange
from core.common import load_trails
from core.common import is_local
from core.common import get_text
from core.common import get_ex_message
from core.common import check_whitelisted
from core.common import check_sudo
from core.common import check_connection
from core.attribdict import AttribDict
from core.addr import addr_port
from core.addr import inet_ntoa6
import traceback
import time
import threading
import struct
import subprocess
import socket
import re
import platform
import os
import optparse
import mmap
import math
import inspect
import cProfile

import sys

sys.dont_write_bytecode = True


_buffer = None
_caps = []
_connect_sec = 0
_connect_src_dst = {}
_connect_src_details = {}
_count = 0
_locks = AttribDict()
_multiprocessing = None
_n = None
_result_cache = LRUDict(MAX_RESULT_CACHE_ENTRIES)
_local_cache = {}
_last_syn = None
_last_logged_syn = None
_last_udp = None
_last_logged_udp = None
_last_dns_exhaustion = None
_done_count = 0
_done_lock = threading.Lock()
_subdomains = {}
_subdomains_sec = None
_dns_exhausted_domains = set()


try:
    import pcapy
except ImportError:
    if IS_WIN:
        exit("[!] please install 'WinPcap' (e.g. 'http://www.winpcap.org/install/') and Pcapy (e.g. 'https://breakingcode.wordpress.com/?s=pcapy')")
    else:
        msg = "[!] please install 'Pcapy' (e.g. 'sudo pip%s install pcapy')" % (
            '3' if six.PY3 else '2')

        exit(msg)


def _check_domain_member(query, domains):
    parts = query.lower().split('.')

    for i in xrange(0, len(parts)):
        domain = '.'.join(parts[i:])
        if domain in domains:
            return True

    return False


def _check_domain_whitelisted(query):
    result = _result_cache.get((CACHE_TYPE.DOMAIN_WHITELISTED, query))

    if result is None:
        result = _check_domain_member(
            re.split(r"(?i)[^A-Z0-9._-]", query or "")[0], WHITELIST)
        _result_cache[(CACHE_TYPE.DOMAIN_WHITELISTED, query)] = result

    return result


def _check_domain(query, sec, usec, src_ip, src_port, dst_ip, dst_port, proto, packet=None):
    if query:
        query = query.lower()
        if ':' in query:
            query = query.split(':', 1)[0]

    if query.replace('.', "").isdigit():  # IP address
        return

    if _result_cache.get((CACHE_TYPE.DOMAIN, query)) == False:
        return

    result = False
    if re.search(VALID_DNS_NAME_REGEX, query) is not None and not _check_domain_whitelisted(query):
        parts = query.split('.')

        if ".onion." in query:
            trail = re.sub(r"(\.onion)(\..*)", r"\1(\2)", query)
            _ = trail.split('(')[0]
            if _ in trails:
                result = True
                flag = 1
                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, proto,
                          TRAIL.DNS, trail, trails[_][0], trails[_][1]), packet)

        # Reference: https://www.virustotal.com/gui/domain/ip-adress.com/relations
        elif query.endswith(".ip-adress.com"):
            _ = '.'.join(parts[:-2])
            trail = "%s(.ip-adress.com)" % _
            if _ in trails:
                result = True
                flag = 2
                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, proto,
                          TRAIL.DNS, trail, trails[_][0], trails[_][1]), packet)

        if not result:
            for i in xrange(0, len(parts)):
                domain = '.'.join(parts[i:])
                if domain in trails:
                    if domain == query:
                        trail = domain
                    else:
                        _ = ".%s" % domain
                        trail = "(%s)%s" % (query[:-len(_)], _)

                    # e.g. ns2.nobel.su
                    if not (re.search(r"(?i)\A([rd]?ns|nf|mx|nic)\d*\.", query) and any(_ in trails.get(domain, " ")[0] for _ in ("suspicious", "sinkhole"))):
                        # e.g. noip.com
                        if not ((query == trail or parts[0] == "www") and any(_ in trails.get(domain, " ")[0] for _ in ("dynamic", "free web"))):
                            result = True
                            flag = 3
                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, proto,
                                      TRAIL.DNS, trail, trails[domain][0], trails[domain][1]), packet)
                            break

        if not result and config.USE_HEURISTICS:
            if len(parts[0]) > SUSPICIOUS_DOMAIN_LENGTH_THRESHOLD and '-' not in parts[0]:
                trail = None

                if len(parts) > 2:
                    trail = "(%s).%s" % (
                        '.'.join(parts[:-2]), '.'.join(parts[-2:]))
                elif len(parts) == 2:
                    trail = "(%s).%s" % (parts[0], parts[1])
                else:
                    trail = query

                if trail and not any(_ in trail for _ in WHITELIST_LONG_DOMAIN_NAME_KEYWORDS):
                    result = True
                    flag = 4
                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, proto,
                              TRAIL.DNS, trail, "long domain (suspicious)", "(heuristic)"), packet)

        if not result and trails._regex:
            match = re.search(trails._regex, query)
            if match:
                group, trail = [_ for _ in match.groupdict().items() if _[
                    1] is not None][0]
                candidate = trails._regex.split("(?P<")[int(group[1:]) + 1]
                candidate = candidate.split('>', 1)[-1].rstrip('|')[:-1]
                if candidate in trails:
                    result = True
                    trail = match.group(0)

                    prefix, suffix = query[:match.start()], query[match.end():]
                    if prefix:
                        trail = "(%s)%s" % (prefix, trail)
                    if suffix:
                        trail = "%s(%s)" % (trail, suffix)

                    trail = trail.replace(".)", ").")
                    flag = 5
                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, proto,
                              TRAIL.DNS, trail, trails[candidate][0], trails[candidate][1]), packet)
    
    if result == False:
        _result_cache[(CACHE_TYPE.DOMAIN, query)] = False
    if(flag == 0):
            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS,
                                                                          _, "UNKNOWN_TRAFFIC", "(heuristic)"), packet)

def _get_local_prefix():
    _sources = set(_.split('~')[0] for _ in _connect_src_dst.keys())
    _candidates = [re.sub(r"\d+\.\d+\Z", "", _) for _ in _sources]
    _ = sorted(((_candidates.count(_), _)
               for _ in set(_candidates)), reverse=True)
    result = _[0][1] if _ else ""

    if result:
        _result_cache[(CACHE_TYPE.LOCAL_PREFIX, "")] = result
    else:
        result = _result_cache.get((CACHE_TYPE.LOCAL_PREFIX, ""))

    return result or '_'

    

def _process_packet(packet, sec, usec, ip_offset):
    """
    Processes single (raw) IP layer data
    """

    global _connect_sec
    global _last_syn
    global _last_logged_syn
    global _last_udp
    global _last_logged_udp
    global _last_dns_exhaustion
    global _subdomains_sec
    flag = 0

    try:
        if config.USE_HEURISTICS:
            if _locks.connect_sec:
                _locks.connect_sec.acquire()

            connect_sec = _connect_sec
            _connect_sec = sec

            if _locks.connect_sec:
                _locks.connect_sec.release()

            if sec > connect_sec:
                for key in _connect_src_dst:
                    _src_ip, _dst = key.split('~')
                    if not _dst.isdigit() and len(_connect_src_dst[key]) > PORT_SCANNING_THRESHOLD:
                        if not check_whitelisted(_src_ip):
                            _dst_ip = _dst
                            for _ in _connect_src_details[key]:
                                flag = 6
                                log_event((sec, usec, _src_ip, _[2], _dst_ip, _[
                                          3], PROTO.TCP, TRAIL.IP, _src_ip, "potential port scanning", "(heuristic)"), packet)
                    elif len(_connect_src_dst[key]) > INFECTION_SCANNING_THRESHOLD:
                        _dst_port = _dst
                        _dst_ip = [_[-1] for _ in _connect_src_details[key]]
                        _src_port = [_[-2] for _ in _connect_src_details[key]]

                        if len(_dst_ip) == len(set(_dst_ip)):
                            if _src_ip.startswith(_get_local_prefix()):
                                flag = 7
                                log_event((sec, usec, _src_ip, _src_port[0], _dst_ip[0], _dst_port, PROTO.TCP,
                                          TRAIL.PORT, _dst_port, "potential infection", "(heuristic)"), packet)

                _connect_src_dst.clear()
                _connect_src_details.clear()
        
        ip_data = packet[ip_offset:]
        ip_version = ord(ip_data[0:1]) >> 4
        localhost_ip = LOCALHOST_IP[ip_version]

        if ip_version == 0x04:  # IPv4
            ip_header = struct.unpack("!BBHHHBBH4s4s", ip_data[:20])
            fragment_offset = ip_header[4] & 0x1fff
            if fragment_offset != 0:
                return
            iph_length = (ip_header[0] & 0xf) << 2
            protocol = ip_header[6]
            src_ip = socket.inet_ntoa(ip_header[8])
            dst_ip = socket.inet_ntoa(ip_header[9])
        elif ip_version == 0x06:  # IPv6
            # Reference: http://chrisgrundemann.com/index.php/2012/introducing-ipv6-understanding-ipv6-addresses/
            ip_header = struct.unpack("!BBHHBB16s16s", ip_data[:40])
            iph_length = 40
            protocol = ip_header[4]
            src_ip = inet_ntoa6(ip_header[6])
            dst_ip = inet_ntoa6(ip_header[7])
        else:
            return

        if protocol == socket.IPPROTO_TCP:  # TCP
            src_port, dst_port, _, _, doff_reserved, flags = struct.unpack(
                "!HHLLBB", ip_data[iph_length:iph_length+14])

            if flags != 2 and config.plugin_functions:
                if dst_ip in trails:
                    flag = 8
                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.IP,
                              dst_ip, trails[dst_ip][0], trails[dst_ip][1]), packet, skip_write=True)
                elif src_ip in trails and dst_ip != localhost_ip:
                    flag = 9
                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.IP,
                              src_ip, trails[src_ip][0], trails[src_ip][1]), packet, skip_write=True)

            if flags == 2:  # SYN set (only)
                _ = _last_syn
                _last_syn = (sec, src_ip, src_port, dst_ip, dst_port)
                if _ == _last_syn:  # skip bursts
                    return

                if dst_ip in trails or addr_port(dst_ip, dst_port) in trails:
                    _ = _last_logged_syn
                    _last_logged_syn = _last_syn
                    if _ != _last_logged_syn:
                        trail = addr_port(dst_ip, dst_port)
                        if trail not in trails:
                            trail = dst_ip
                        if not any(_ in trails[trail][0] for _ in ("attacker",)) and not ("parking site" in trails[trail][0] and dst_port not in (80, 443)):
                            flag = 10
                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                      TRAIL.IP if ':' not in trail else TRAIL.IPORT, trail, trails[trail][0], trails[trail][1]), packet)

                elif (src_ip in trails or addr_port(src_ip, src_port) in trails) and dst_ip != localhost_ip:
                    _ = _last_logged_syn
                    _last_logged_syn = _last_syn
                    if _ != _last_logged_syn:
                        trail = addr_port(src_ip, src_port)
                        if trail not in trails:
                            trail = src_ip
                        if not any(_ in trails[trail][0] for _ in ("malware",)):
                            flag = 11
                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                      TRAIL.IP if ':' not in trail else TRAIL.IPORT, trail, trails[trail][0], trails[trail][1]), packet)

                if config.USE_HEURISTICS:
                    if dst_ip != localhost_ip:
                        key = "%s~%s" % (src_ip, dst_ip)
                        if key not in _connect_src_dst:
                            _connect_src_dst[key] = set()
                            _connect_src_details[key] = set()
                        _connect_src_dst[key].add(dst_port)
                        _connect_src_details[key].add(
                            (sec, usec, src_port, dst_port))

                        if dst_port in POTENTIAL_INFECTION_PORTS:
                            key = "%s~%s" % (src_ip, dst_port)
                            if key not in _connect_src_dst:
                                _connect_src_dst[key] = set()
                                _connect_src_details[key] = set()
                            _connect_src_dst[key].add(dst_ip)
                            _connect_src_details[key].add(
                                (sec, usec, src_port, dst_ip))
            else:
                tcph_length = doff_reserved >> 4
                h_size = iph_length + (tcph_length << 2)
                tcp_data = get_text(ip_data[h_size:])

                if tcp_data.startswith("HTTP/"):
                    match = re.search(GENERIC_SINKHOLE_REGEX, tcp_data[:2000])
                    if match:
                        trail = match.group(0)
                        flag = 12
                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                  TRAIL.HTTP, trail, "sinkhole response (malware)", "(heuristic)"), packet)
                    else:
                        index = tcp_data.find("<title>")
                        if index >= 0:
                            title = tcp_data[index +
                                             len("<title>"):tcp_data.find("</title>", index)]
                            if all(_ in title.lower() for _ in ("this domain", "has been seized")):
                                flag = 13
                                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                          TRAIL.HTTP, title, "seized domain (suspicious)", "(heuristic)"), packet)

                    content_type = None
                    first_index = tcp_data.find("\r\nContent-Type:")
                    if first_index >= 0:
                        first_index = first_index + len("\r\nContent-Type:")
                        last_index = tcp_data.find("\r\n", first_index)
                        if last_index >= 0:
                            content_type = tcp_data[first_index:last_index].strip(
                            ).lower()

                    if content_type and content_type in SUSPICIOUS_CONTENT_TYPES:
                        flag = 14
                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.HTTP,
                                  content_type, "content type (suspicious)", "(heuristic)"), packet)

                method, path = None, None

                if " HTTP/" in tcp_data:
                    index = tcp_data.find("\r\n")
                    if index >= 0:
                        line = tcp_data[:index]
                        if line.count(' ') == 2 and " HTTP/" in line:
                            method, path, _ = line.split(' ')

                if method and path:
                    post_data = None
                    host = dst_ip
                    first_index = tcp_data.find("\r\nHost:")
                    path = path.lower()

                    if first_index >= 0:
                        first_index = first_index + len("\r\nHost:")
                        last_index = tcp_data.find("\r\n", first_index)
                        if last_index >= 0:
                            host = tcp_data[first_index:last_index]
                            host = host.strip().lower()
                            if host.endswith(":80"):
                                host = host[:-3]
                            if host and host[0].isalpha() and dst_ip in trails:
                                flag = 15
                                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.IP, "%s (%s)" % (
                                    dst_ip, host.split(':')[0]), trails[dst_ip][0], trails[dst_ip][1]), packet)
                            elif re.search(r"\A\d+\.[0-9.]+\Z", host or "") and re.search(SUSPICIOUS_DIRECT_IP_URL_REGEX, "%s%s" % (host, path)):
                                if not _dst_ip.startswith(_get_local_prefix()):
                                    trail = "(%s)%s" % (host, path)
                                    flag = 16
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.HTTP,
                                              trail, "potential iot-malware download (suspicious)", "(heuristic)"), packet)
                                    return
                            elif config.CHECK_HOST_DOMAINS:
                                _check_domain(
                                    host, sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, packet)
                    elif config.USE_HEURISTICS and config.CHECK_MISSING_HOST:
                        flag = 17
                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.HTTP, "%s%s" % (
                            host, path), "missing host header (suspicious)", "(heuristic)"), packet)

                    index = tcp_data.find("\r\n\r\n")
                    if index >= 0:
                        post_data = tcp_data[index + 4:]

                    if config.USE_HEURISTICS and dst_port == 80 and path.startswith("http://") and any(_ in path for _ in SUSPICIOUS_PROXY_PROBE_PRE_CONDITION) and not _check_domain_whitelisted(path.split('/')[2]):
                        trail = re.sub(
                            r"(http://[^/]+/)(.+)", r"\g<1>(\g<2>)", path)
                        trail = re.sub(r"(http://)([^/(]+)", lambda match: "%s%s" % (
                            match.group(1), match.group(2).split(':')[0].rstrip('.')), trail)
                        flag = 18
                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.HTTP,
                                  trail, "potential proxy probe (suspicious)", "(heuristic)"), packet)
                        return
                    elif "://" in path:
                        unquoted_path = _urllib.parse.unquote(path)

                        key = "code execution"
                        if key not in _local_cache:
                            _local_cache[key] = next(
                                _[1] for _ in SUSPICIOUS_HTTP_REQUEST_REGEXES if "code execution" in _[0])

                        # NOTE: to prevent malware domain FPs in case of outside scanners
                        if re.search(_local_cache[key], unquoted_path, re.I) is None:
                            url = path.split("://", 1)[1]

                            if '/' not in url:
                                url = "%s/" % url

                            host, path = url.split('/', 1)
                            if host.endswith(":80"):
                                host = host[:-3]
                            path = "/%s" % path
                            proxy_domain = host.split(':')[0]
                            _check_domain(
                                proxy_domain, sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, packet)
                    elif method == "CONNECT":
                        if '/' in path:
                            host, path = path.split('/', 1)
                            path = "/%s" % path
                        else:
                            host, path = path, '/'
                        if host.endswith(":80"):
                            host = host[:-3]
                        url = "%s%s" % (host, path)
                        proxy_domain = host.split(':')[0]
                        _check_domain(proxy_domain, sec, usec, src_ip,
                                      src_port, dst_ip, dst_port, PROTO.TCP, packet)
                    else:
                        url = "%s%s" % (host, path)

                    if config.USE_HEURISTICS:
                        user_agent, result = None, None

                        first_index = tcp_data.find("\r\nUser-Agent:")
                        if first_index >= 0:
                            first_index = first_index + len("\r\nUser-Agent:")
                            last_index = tcp_data.find("\r\n", first_index)
                            if last_index >= 0:
                                user_agent = tcp_data[first_index:last_index]
                                user_agent = _urllib.parse.unquote(
                                    user_agent).strip()

                        if user_agent:
                            result = _result_cache.get(
                                (CACHE_TYPE.USER_AGENT, user_agent))
                            if result is None:
                                if re.search(WHITELIST_UA_REGEX, user_agent, re.I) is None:
                                    match = re.search(
                                        SUSPICIOUS_UA_REGEX, user_agent)
                                    if match:
                                        def _(value):
                                            return value.rstrip('\\').replace('(', "\\(").replace(')', "\\)")

                                        parts = user_agent.split(
                                            match.group(0), 1)

                                        if len(parts) > 1 and parts[0] and parts[-1]:
                                            result = _result_cache[(CACHE_TYPE.USER_AGENT, user_agent)] = "%s (%s)" % (
                                                _(match.group(0)), _(user_agent))
                                        else:
                                            result = _result_cache[(CACHE_TYPE.USER_AGENT, user_agent)] = _(
                                                match.group(0)).join(("(%s)" if part else "%s") % _(part) for part in parts)
                                if not result:
                                    _result_cache[(
                                        CACHE_TYPE.USER_AGENT, user_agent)] = False

                            if result:
                                flag = 19
                                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                          TRAIL.UA, result, "user agent (suspicious)", "(heuristic)"), packet)

                    if not _check_domain_whitelisted(host):
                        unquoted_path = _urllib.parse.unquote(path)
                        unquoted_post_data = _urllib.parse.unquote(
                            post_data or "")

                        checks = [path.rstrip('/')]
                        if '?' in path:
                            checks.append(path.split('?')[0].rstrip('/'))

                            if '=' in path:
                                checks.append(path[:path.index('=') + 1])
                        elif post_data:
                            checks.append("%s?%s" %
                                          (path, unquoted_post_data.lower()))

                        # _ = os.path.splitext(checks[-1])       # causing FPs in cases like elf_mirai - /juno if legit /juno.php is accessed
                        # if _[1]:
                            # checks.append(_[0])

                        if checks[-1].count('/') > 1:
                            checks.append(checks[-1][:checks[-1].rfind('/')])
                            checks.append(
                                checks[0][checks[0].rfind('/'):].split('?')[0])

                        for check in filter(None, checks):
                            for _ in ("", host):
                                check = "%s%s" % (_, check)
                                if check in trails:
                                    if '?' not in path and '?' in check and post_data:
                                        trail = "%s(%s \\(%s %s\\))" % (
                                            host, path, method, post_data.strip())
                                        flag = 20
                                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                                  TRAIL.HTTP, trail, trails[check][0], trails[check][1]))
                                    else:
                                        parts = url.split(check)
                                        other = ("(%s)" %
                                                 _ if _ else _ for _ in parts)
                                        trail = check.join(other)
                                        flag = 21
                                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                                  TRAIL.URL, trail, trails[check][0], trails[check][1]))

                                    return

                        if "%s/" % host in trails:
                            trail = "%s/" % host
                            flag = 22
                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                      TRAIL.URL, trail, trails[trail][0], trails[trail][1]))
                            return

                        if config.USE_HEURISTICS:
                            match = re.search(
                                r"\bX-Forwarded-For:\s*([0-9.]+)".encode(), packet, re.I)
                            if match:
                                src_ip = "%s,%s" % (src_ip, match.group(1))

                            for char in SUSPICIOUS_HTTP_REQUEST_FORCE_ENCODE_CHARS:
                                replacement = SUSPICIOUS_HTTP_REQUEST_FORCE_ENCODE_CHARS[char]
                                path = path.replace(char, replacement)
                                if post_data:
                                    post_data = post_data.replace(
                                        char, replacement)

                            if not any(_ in unquoted_path.lower() for _ in WHITELIST_HTTP_REQUEST_PATHS):
                                if any(_ in unquoted_path for _ in SUSPICIOUS_HTTP_REQUEST_PRE_CONDITION):
                                    found = _result_cache.get(
                                        (CACHE_TYPE.PATH, unquoted_path))
                                    if found is None:
                                        for desc, regex in SUSPICIOUS_HTTP_REQUEST_REGEXES:
                                            if re.search(regex, unquoted_path, re.I | re.DOTALL):
                                                found = desc
                                                break
                                        _result_cache[(
                                            CACHE_TYPE.PATH, unquoted_path)] = found or ""
                                    if found:
                                        trail = "%s(%s)" % (host, path)
                                        flag = 23
                                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                                  TRAIL.URL, trail, "%s (suspicious)" % found, "(heuristic)"), packet)
                                        return

                                if any(_ in unquoted_post_data for _ in SUSPICIOUS_HTTP_REQUEST_PRE_CONDITION):
                                    found = _result_cache.get(
                                        (CACHE_TYPE.POST_DATA, unquoted_post_data))
                                    if found is None:
                                        for desc, regex in SUSPICIOUS_HTTP_REQUEST_REGEXES:
                                            if re.search(regex, unquoted_post_data, re.I | re.DOTALL):
                                                found = desc
                                                break
                                        _result_cache[(
                                            CACHE_TYPE.POST_DATA, unquoted_post_data)] = found or ""
                                    if found:
                                        trail = "%s(%s \\(%s %s\\))" % (
                                            host, path, method, post_data.strip())
                                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                                  TRAIL.HTTP, trail, "%s (suspicious)" % found, "(heuristic)"), packet)
                                        return

                            if '.' in path:
                                _ = _urllib.parse.urlparse(
                                    "http://%s" % url)  # dummy scheme
                                path = path.lower()
                                filename = _.path.split('/')[-1]
                                name, extension = os.path.splitext(filename)
                                trail = "%s(%s)" % (host, path)
                                if extension and extension in SUSPICIOUS_DIRECT_DOWNLOAD_EXTENSIONS and not any(_ in path for _ in WHITELIST_DIRECT_DOWNLOAD_KEYWORDS) and '=' not in _.query and len(name) < 10:
                                    flag = 24
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.URL,
                                              trail, "direct %s download (suspicious)" % extension, "(heuristic)"), packet)
                                elif filename in WEB_SHELLS:
                                    flag = 25
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.URL,
                                              trail, "potential web shell (suspicious)", "(heuristic)"), packet)
                                else:
                                    for desc, regex in SUSPICIOUS_HTTP_PATH_REGEXES:
                                        if re.search(regex, filename, re.I):
                                            flag = 26
                                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP,
                                                      TRAIL.URL, trail, "%s (suspicious)" % desc, "(heuristic)"), packet)
                                            break

        elif protocol == socket.IPPROTO_UDP:  # UDP
            _ = ip_data[iph_length:iph_length + 4]
            if len(_) < 4:
                return

            src_port, dst_port = struct.unpack("!HH", _)

            _ = _last_udp
            _last_udp = (sec, src_ip, src_port, dst_ip, dst_port)
            if _ == _last_udp:  # skip bursts
                return

            if src_port != 53 and dst_port != 53:  # not DNS
                if dst_ip in trails:
                    trail = dst_ip
                elif src_ip in trails:
                    trail = src_ip
                else:
                    trail = None

                if trail:
                    _ = _last_logged_udp
                    _last_logged_udp = _last_udp
                    if _ != _last_logged_udp:
                        if not any(_ in trails[trail][0] for _ in ("malware",)):
                            flag = 27
                            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP,
                                      TRAIL.IP, trail, trails[trail][0], trails[trail][1]), packet)

            else:
                dns_data = ip_data[iph_length + 8:]

                # Reference: http://www.ccs.neu.edu/home/amislove/teaching/cs4700/fall09/handouts/project1-primer.pdf
                if len(dns_data) > 6:
                    qdcount = struct.unpack("!H", dns_data[4:6])[0]
                    if qdcount > 0:
                        offset = 12
                        query = ""

                        while len(dns_data) > offset:
                            length = ord(dns_data[offset:offset + 1])
                            if not length:
                                query = query[:-1]
                                break
                            query += get_text(dns_data[offset +
                                              1:offset + length + 1]) + '.'
                            offset += length + 1

                        query = query.lower()

                        if not query or re.search(VALID_DNS_NAME_REGEX, query) is None or any(_ in query for _ in (".intranet.",)) or query.split('.')[-1] in IGNORE_DNS_QUERY_SUFFIXES:
                            return

                        parts = query.split('.')

                        # standard query (both recursive and non-recursive)
                        if ord(dns_data[2:3]) & 0xfa == 0x00:
                            type_, class_ = struct.unpack(
                                "!HH", dns_data[offset + 1:offset + 5])

                            if len(parts) > 2:
                                if len(parts) > 3 and len(parts[-2]) <= 3:
                                    domain = '.'.join(parts[-3:])
                                else:
                                    domain = '.'.join(parts[-2:])

                                # e.g. <hash>.hashserver.cs.trendmicro.com
                                if not _check_domain_whitelisted(domain):
                                    if (sec - (_subdomains_sec or 0)) > DAILY_SECS:
                                        _subdomains.clear()
                                        _dns_exhausted_domains.clear()
                                        _subdomains_sec = sec

                                    subdomains = _subdomains.get(domain)

                                    if not subdomains:
                                        subdomains = _subdomains[domain] = set(
                                        )

                                    if not re.search(r"\A\d+\-\d+\-\d+\-\d+\Z", parts[0]):
                                        if len(subdomains) < DNS_EXHAUSTION_THRESHOLD:
                                            subdomains.add(
                                                '.'.join(parts[:-2]))
                                        else:
                                            if (sec - (_last_dns_exhaustion or 0)) > 60:
                                                trail = "(%s).%s" % (
                                                    '.'.join(parts[:-2]), '.'.join(parts[-2:]))
                                                # generic check for DNSBLs
                                                if re.search(r"bl\b", trail) is None:
                                                    # generic check for local DNS resolutions
                                                    if not any(_ in subdomains for _ in LOCAL_SUBDOMAIN_LOOKUPS):
                                                        flag = 28
                                                        log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS,
                                                                  trail, "potential dns exhaustion (suspicious)", "(heuristic)"), packet)
                                                        _dns_exhausted_domains.add(
                                                            domain)
                                                        _last_dns_exhaustion = sec

                                            return

                            # Reference: http://en.wikipedia.org/wiki/List_of_DNS_record_types
                            # Type not in (PTR, AAAA), Class IN
                            if type_ not in (12, 28) and class_ == 1:
                                if addr_port(dst_ip, dst_port) in trails:
                                    trail = addr_port(dst_ip, dst_port)
                                    flag = 29
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.IPORT, "%s (%s)" % (
                                        dst_ip, query), trails[trail][0], trails[trail][1]), packet)
                                elif dst_ip in trails:
                                    flag = 30
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.IP, "%s (%s)" % (
                                        dst_ip, query), trails[dst_ip][0], trails[dst_ip][1]), packet)
                                elif src_ip in trails:
                                    flag = 31
                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP,
                                              TRAIL.IP, src_ip, trails[src_ip][0], trails[src_ip][1]), packet)

                                _check_domain(
                                    query, sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, packet)

                        elif config.USE_HEURISTICS:
                            if ord(dns_data[2:3]) & 0x80:  # standard response
                                # recursion available, no error
                                if ord(dns_data[3:4]) == 0x80:
                                    _ = offset + 5
                                    try:
                                        while _ < len(dns_data):
                                            # Type A
                                            if ord(dns_data[_:_ + 1]) & 0xc0 != 0 and dns_data[_ + 2] == "\00" and dns_data[_ + 3] == "\x01":
                                                break
                                            else:
                                                _ += 12 + \
                                                    struct.unpack(
                                                        "!H", dns_data[_ + 10: _ + 12])[0]

                                        _ = dns_data[_ + 12:_ + 16]
                                        if _:
                                            answer = socket.inet_ntoa(_)
                                            if answer in trails and not _check_domain_whitelisted(query):
                                                _ = trails[answer]
                                                if "sinkhole" in _[0]:
                                                    trail = "(%s).%s" % (
                                                        '.'.join(parts[:-1]), '.'.join(parts[-1:]))
                                                    flag = 32
                                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS, trail, "sinkholed by %s (malware)" % _[
                                                              0].split(" ")[1], "(heuristic)"), packet)  # (e.g. kitro.pl, devomchart.com, jebena.ananikolic.su, vuvet.cn)
                                                elif "parking" in _[0]:
                                                    trail = "(%s).%s" % (
                                                        '.'.join(parts[:-1]), '.'.join(parts[-1:]))
                                                    flag = 33
                                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP,
                                                              TRAIL.DNS, trail, "parked site (suspicious)", "(heuristic)"), packet)
                                    except IndexError:
                                        pass

                                # recursion available, no such name
                                elif ord(dns_data[3:4]) == 0x83:
                                    if '.'.join(parts[-2:]) not in _dns_exhausted_domains and not _check_domain_whitelisted(query) and not _check_domain_member(query, trails):
                                        if parts[-1].isdigit():
                                            return

                                        # generic check for DNSBL IP lookups
                                        if not (len(parts) > 4 and all(_.isdigit() and int(_) < 256 for _ in parts[:4])):
                                            # prevent FPs caused by local queries
                                            if not is_local(dst_ip):
                                                for _ in filter(None, (query, "*.%s" % '.'.join(parts[-2:]) if query.count('.') > 1 else None)):
                                                    if _ not in NO_SUCH_NAME_COUNTERS or NO_SUCH_NAME_COUNTERS[_][0] != sec // 3600:
                                                        NO_SUCH_NAME_COUNTERS[_] = [
                                                            sec // 3600, 1, set()]
                                                    else:
                                                        NO_SUCH_NAME_COUNTERS[_][1] += 1
                                                        NO_SUCH_NAME_COUNTERS[_][2].add(
                                                            query)

                                                        if NO_SUCH_NAME_COUNTERS[_][1] > NO_SUCH_NAME_PER_HOUR_THRESHOLD:
                                                            if _.startswith("*."):
                                                                trail = "%s%s" % ("(%s)" % ','.join(item.replace(
                                                                    _[1:], "") for item in NO_SUCH_NAME_COUNTERS[_][2]), _[1:])
                                                                # generic check for local DNS resolutions
                                                                if not any(subdomain in trail for subdomain in LOCAL_SUBDOMAIN_LOOKUPS):
                                                                    flag = 34
                                                                    log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS,
                                                                              trail, "excessive no such domain (suspicious)", "(heuristic)"), packet)
                                                                for item in NO_SUCH_NAME_COUNTERS[_][2]:
                                                                    try:
                                                                        del NO_SUCH_NAME_COUNTERS[item]
                                                                    except KeyError:
                                                                        pass
                                                            else:
                                                                flag = 35
                                                                log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS,
                                                                          _, "excessive no such domain (suspicious)", "(heuristic)"), packet)

                                                            try:
                                                                del NO_SUCH_NAME_COUNTERS[_]
                                                            except KeyError:
                                                                pass

                                                            break

                                            if len(parts) == 2 and parts[0] and '-' not in parts[0]:
                                                part = parts[0]
                                                trail = "(%s).%s" % (
                                                    parts[0], parts[1])

                                                result = _result_cache.get(
                                                    part)

                                                if result is None:
                                                    # Reference: https://github.com/exp0se/dga_detector
                                                    probabilities = (
                                                        float(part.count(c)) / len(part) for c in set(_ for _ in part))
                                                    entropy = - \
                                                        sum(p * math.log(p) / math.log(2.0)
                                                            for p in probabilities)
                                                    if entropy > SUSPICIOUS_DOMAIN_ENTROPY_THRESHOLD:
                                                        result = "entropy threshold no such domain (suspicious)"

                                                    if not result:
                                                        if sum(_ in CONSONANTS for _ in part) > SUSPICIOUS_DOMAIN_CONSONANT_THRESHOLD:
                                                            result = "consonant threshold no such domain (suspicious)"

                                                    _result_cache[part] = result or False

                                                if result:
                                                    flag = 36
                                                    log_event(
                                                        (sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.UDP, TRAIL.DNS, trail, result, "(heuristic)"), packet)

        elif protocol in IPPROTO_LUT:  # non-TCP/UDP (e.g. ICMP)
            if protocol == socket.IPPROTO_ICMP:
                if ord(ip_data[iph_length:iph_length + 1]) != 0x08:  # Non-echo request
                    return
            elif protocol == socket.IPPROTO_ICMPV6:
                if ord(ip_data[iph_length:iph_length + 1]) != 0x80:  # Non-echo request
                    return

            if dst_ip in trails:
                flag = 37
                log_event((sec, usec, src_ip, '-', dst_ip, '-',
                          IPPROTO_LUT[protocol], TRAIL.IP, dst_ip, trails[dst_ip][0], trails[dst_ip][1]), packet)
            elif src_ip in trails:
                flag = 38
                log_event((sec, usec, src_ip, '-', dst_ip, '-',
                          IPPROTO_LUT[protocol], TRAIL.IP, src_ip, trails[src_ip][0], trails[src_ip][1]), packet)
        if(flag == 0):
            log_event((sec, usec, src_ip, src_port, dst_ip, dst_port, PROTO.TCP, TRAIL.DNS,
                                                                          _, "UNKNOWN_TRAFFIC", "(heuristic)"), packet)


    except struct.error:
        pass

    except Exception:
        if config.SHOW_DEBUG:
            traceback.print_exc()

   
     
def init():
    """
    Performs sensor initialization
    """

    global _multiprocessing

    try:
        import multiprocessing

        if config.PROCESS_COUNT > 1 and not config.profile:
            _multiprocessing = multiprocessing
    except (ImportError, OSError, NotImplementedError):
        pass

    def update_timer():
        retries = 0
        if not config.no_updates:
            while retries < CHECK_CONNECTION_MAX_RETRIES and not check_connection():
                sys.stdout.write(
                    "[!] can't update because of lack of Internet connection (waiting..." if not retries else '.')
                sys.stdout.flush()
                time.sleep(10)
                retries += 1

            if retries:
                print(")")

        if config.no_updates or retries == CHECK_CONNECTION_MAX_RETRIES:
            if retries == CHECK_CONNECTION_MAX_RETRIES:
                print("[x] going to continue without online update")
            _ = update_trails(offline=True)
        else:
            _ = update_trails()
            update_ipcat()

        if _:
            trails.clear()
            trails.update(_)
        elif not trails:
            _ = load_trails()
            trails.update(_)

        _regex = ""
        for trail in trails:
            if "static" in trails[trail][1]:
                if re.search(r"[\].][*+]|\[[a-z0-9_.\-]+\]", trail, re.I):
                    try:
                        re.compile(trail)
                    except:
                        pass
                    else:
                        if re.escape(trail) != trail:
                            index = _regex.count("(?P<g")
                            if index < 100:  # Reference: https://stackoverflow.com/questions/478458/python-regular-expressions-with-more-than-100-groups
                                _regex += "|(?P<g%s>%s)" % (index, trail)

        trails._regex = _regex.strip('|')

        thread = threading.Timer(config.UPDATE_PERIOD, update_timer)
        thread.daemon = True
        thread.start()

    create_log_directory()
    get_error_log_handle()

    check_memory()

    msg = "[i] using '%s' for trail storage" % config.TRAILS_FILE
    if os.path.isfile(config.TRAILS_FILE):
        mtime = time.gmtime(os.path.getmtime(config.TRAILS_FILE))
        msg += " (last modification: '%s')" % time.strftime(HTTP_TIME_FORMAT, mtime)

    print(msg)

    update_timer()

    if not config.DISABLE_CHECK_SUDO and check_sudo() is False:
        exit("[!] please run '%s' with sudo/Administrator privileges" % __file__)

    if config.plugins:
        config.plugin_functions = []
        for plugin in re.split(r"[,;]", config.plugins):
            plugin = plugin.strip()
            found = False

            for _ in (plugin, os.path.join("plugins", plugin), os.path.join("plugins", "%s.py" % plugin)):
                if os.path.isfile(_):
                    plugin = _
                    found = True
                    break

            if not found:
                exit("[!] plugin script '%s' not found" % plugin)
            else:
                dirname, filename = os.path.split(plugin)
                dirname = os.path.abspath(dirname)
                if not os.path.exists(os.path.join(dirname, '__init__.py')):
                    exit(
                        "[!] empty file '__init__.py' required inside directory '%s'" % dirname)

                if not filename.endswith(".py"):
                    exit(
                        "[!] plugin script '%s' should have an extension '.py'" % filename)

                if dirname not in sys.path:
                    sys.path.insert(0, dirname)

                try:
                    module = __import__(
                        filename[:-3].encode(sys.getfilesystemencoding()))
                except (ImportError, SyntaxError) as msg:
                    exit("[!] unable to import plugin script '%s' (%s)" %
                         (filename, msg))

                found = False
                for name, function in inspect.getmembers(module, inspect.isfunction):
                    if name == "plugin" and not set(inspect.getargspec(function).args) & set(("event_tuple', 'packet")):
                        found = True
                        config.plugin_functions.append(function)
                        function.__name__ = module.__name__

                if not found:
                    exit(
                        "[!] missing function 'plugin(event_tuple, packet)' in plugin script '%s'" % filename)

    if config.pcap_file:
        for _ in config.pcap_file.split(','):
            _caps.append(pcapy.open_offline(_))
    else:
        interfaces = set(_.strip()
                         for _ in config.MONITOR_INTERFACE.split(','))

        if (config.MONITOR_INTERFACE or "").lower() == "any":
            if IS_WIN or "any" not in pcapy.findalldevs():
                print(
                    "[x] virtual interface 'any' missing. Replacing it with all interface names")
                interfaces = pcapy.findalldevs()
            else:
                print("[?] in case of any problems with packet capture on virtual interface 'any', please put all monitoring interfaces to promiscuous mode manually (e.g. 'sudo ifconfig eth0 promisc')")

        for interface in interfaces:
            if interface.lower() != "any" and re.sub(r"(?i)\Anetmap:", "", interface) not in pcapy.findalldevs():
                hint = "[?] available interfaces: '%s'" % ",".join(
                    pcapy.findalldevs())
                exit("[!] interface '%s' not found\n%s" % (interface, hint))

            print("[i] opening interface '%s'" % interface)
            try:
                _caps.append(pcapy.open_live(
                    interface, SNAP_LEN, True, CAPTURE_TIMEOUT))
            except (socket.error, pcapy.PcapError):
                if "permitted" in str(sys.exc_info()[1]):
                    exit("[!] permission problem occurred ('%s')" %
                         sys.exc_info()[1])
                elif "No such device" in str(sys.exc_info()[1]):
                    exit("[!] no such device '%s'" % interface)
                else:
                    raise

    if config.LOG_SERVER and ':' not in config.LOG_SERVER:
        exit("[!] invalid configuration value for 'LOG_SERVER' ('%s')" %
             config.LOG_SERVER)

    if config.SYSLOG_SERVER and not len(config.SYSLOG_SERVER.split(':')) == 2:
        exit("[!] invalid configuration value for 'SYSLOG_SERVER' ('%s')" %
             config.SYSLOG_SERVER)

    if config.CAPTURE_FILTER:
        print("[i] setting capture filter '%s'" % config.CAPTURE_FILTER)
        for _cap in _caps:
            try:
                _cap.setfilter(config.CAPTURE_FILTER)
            except:
                pass

    if _multiprocessing:
        _init_multiprocessing()

    if not IS_WIN and not config.DISABLE_CPU_AFFINITY:
        try:
            try:
                mod = int(subprocess.check_output(
                    "grep -c ^processor /proc/cpuinfo", stderr=subprocess.STDOUT, shell=True).strip())
                used = subprocess.check_output(
                    "for pid in $(ps aux | grep python | grep sensor.py | grep -E -o 'root[ ]*[0-9]*' | tr -d '[:alpha:] '); do schedtool $pid; done | grep -E -o 'AFFINITY .*' | cut -d ' ' -f 2 | grep -v 0xf", stderr=subprocess.STDOUT, shell=True).strip().split('\n')
                max_used = max(int(_, 16) for _ in used)
                affinity = max(1, (max_used << 1) % 2 ** mod)
            except:
                affinity = 1
            p = subprocess.Popen("schedtool -n -2 -M 2 -p 10 -a 0x%02x %d" % (
                affinity, os.getpid()), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = p.communicate()
            if "not found" in stderr:
                msg, _ = "[?] please install 'schedtool' for better CPU scheduling", platform.linux_distribution()[
                    0].lower()
                for distro, install in {("fedora", "centos"): "sudo yum install schedtool", ("debian", "ubuntu"): "sudo apt-get install schedtool"}.items():
                    if _ in distro:
                        msg += " (e.g. '%s')" % install
                        break
                print(msg)
        except:
            pass


def _init_multiprocessing():
    """
    Inits worker processes used in multiprocessing mode
    """

    global _buffer
    global _n

    if _multiprocessing:
        print("[i] preparing capture buffer...")
        try:
            # http://www.alexonlinux.com/direct-io-in-python
            _buffer = mmap.mmap(-1, config.CAPTURE_BUFFER)

            _ = b"\x00" * MMAP_ZFILL_CHUNK_LENGTH
            for i in xrange(config.CAPTURE_BUFFER // MMAP_ZFILL_CHUNK_LENGTH):
                _buffer.write(_)
            _buffer.seek(0)
        except KeyboardInterrupt:
            raise
        except:
            exit(
                "[!] unable to allocate network capture buffer. Please adjust value of 'CAPTURE_BUFFER'")

        print("[i] creating %d more processes (out of total %d)" %
              (config.PROCESS_COUNT - 1, config.PROCESS_COUNT))
        _n = _multiprocessing.Value('L', lock=False)

        for i in xrange(config.PROCESS_COUNT - 1):
            process = _multiprocessing.Process(target=worker, name=str(i), args=(
                _buffer, _n, i, config.PROCESS_COUNT - 1, _process_packet))
            process.daemon = True
            process.start()
            


def monitor():
    """
    Sniffs/monitors given capturing interface
    """

    print("[o] running...")

    def packet_handler(datalink, header, packet):
        global _count

        ip_offset = None
        try:
            dlt_offset = DLT_OFFSETS[datalink]
        except KeyError:
            log_error("Received unexpected datalink (%d)" %
                      datalink, single=True)
            return

        try:
            if datalink == pcapy.DLT_RAW:
                ip_offset = dlt_offset

            elif datalink == pcapy.DLT_PPP:
                if packet[2:4] in (b"\x00\x21", b"\x00\x57"):  # (IPv4, IPv6)
                    ip_offset = dlt_offset

            elif datalink == pcapy.DLT_NULL:
                if packet[0:4] in (b"\x02\x00\x00\x00", b"\x23\x00\x00\x00"):  # (IPv4, IPv6)
                    ip_offset = dlt_offset

            elif dlt_offset >= 2:
                if packet[dlt_offset - 2:dlt_offset] == b"\x81\x00":  # VLAN
                    dlt_offset += 4
                # (IPv4, IPv6)
                if packet[dlt_offset - 2:dlt_offset] in (b"\x08\x00", b"\x86\xdd"):
                    ip_offset = dlt_offset

        except IndexError:
            pass

        if ip_offset is None:
            return

        try:
            if six.PY3:  # https://github.com/helpsystems/pcapy/issues/37#issuecomment-530795813
                sec, usec = [int(_) for _ in ("%.6f" % time.time()).split('.')]
            else:
                sec, usec = header.getts()

            if _multiprocessing:
                block = struct.pack("=III", sec, usec, ip_offset) + packet

                if _locks.count:
                    _locks.count.acquire()

                write_block(_buffer, _count, block)
                _n.value = _count = _count + 1

                if _locks.count:
                    _locks.count.release()
            else:
                _process_packet(packet, sec, usec, ip_offset)

        except socket.timeout:
            pass

    try:
        def _(_cap):
            global _done_count

            datalink = _cap.datalink()

            if six.PY3 and not config.pcap_file:  # https://github.com/helpsystems/pcapy/issues/37#issuecomment-530795813
                def _loop_handler(header, packet):
                    packet_handler(datalink, header, packet)

                _cap.loop(-1, _loop_handler)
            else:
                while True:
                    success = False
                    try:
                        (header, packet) = _cap.next()
                        if header is not None:
                            success = True
                            packet_handler(datalink, header, packet)
                        elif config.pcap_file:
                            with _done_lock:
                                _done_count += 1
                            break
                    except (pcapy.PcapError, socket.timeout):
                        pass

                    if not success:
                        time.sleep(REGULAR_SENSOR_SLEEP_TIME)

        if config.profile and len(_caps) == 1:
            print("[=] will store profiling results to '%s'..." %
                  config.profile)
            _(_caps[0])
        else:
            if len(_caps) > 1:
                if _multiprocessing:
                    _locks.count = threading.Lock()
                _locks.connect_sec = threading.Lock()

            for _cap in _caps:
                threading.Thread(target=_, args=(_cap,)).start()

            while _caps and not _done_count == (config.pcap_file or "").count(',') + 1:
                time.sleep(1)

        print("[i] all capturing interfaces closed")
    except SystemError as ex:
        if "error return without" in str(ex):
            print("\r[x] stopping (Ctrl-C pressed)")
        else:
            raise
    except KeyboardInterrupt:
        print("\r[x] stopping (Ctrl-C pressed)")
    finally:
        print("\r[i] please wait...")

        if _multiprocessing:
            try:
                for _ in xrange(config.PROCESS_COUNT - 1):
                    write_block(_buffer, _n.value, b"", BLOCK_MARKER.END)
                    _n.value = _n.value + 1
                while _multiprocessing.active_children():
                    time.sleep(REGULAR_SENSOR_SLEEP_TIME)
            except KeyboardInterrupt:
                pass

        if config.pcap_file:
            flush_condensed_events(True)


def main():
    for i in xrange(1, len(sys.argv)):
        if sys.argv[i] == "-q":
            sys.stdout = open(os.devnull, 'w')
        if sys.argv[i] == "-i":
            for j in xrange(i + 2, len(sys.argv)):
                value = sys.argv[j]
                if os.path.isfile(value):
                    sys.argv[i + 1] += ",%s" % value
                    sys.argv[j] = ''
                else:
                    break

    print("%s (sensor) #v%s\n" % (NAME, VERSION))

    parser = optparse.OptionParser(version=VERSION)
    parser.add_option("-c", dest="config_file", default=CONFIG_FILE,
                      help="configuration file (default: '%s')" % os.path.split(CONFIG_FILE)[-1])
    parser.add_option("-i", dest="pcap_file",
                      help="open pcap file for offline analysis")
    parser.add_option("-p", dest="plugins",
                      help="plugin(s) to be used per event")
    parser.add_option("-q", dest="quiet", action="store_true",
                      help="turn off regular output")
    parser.add_option("--console", dest="console", action="store_true",
                      help="print events to console (Note: switch '-q' might be useful)")
    parser.add_option("--no-updates", dest="no_updates",
                      action="store_true", help="disable (online) trail updates")
    parser.add_option("--debug", dest="debug",
                      action="store_true", help=optparse.SUPPRESS_HELP)
    parser.add_option("--profile", dest="profile", help=optparse.SUPPRESS_HELP)
    options, _ = parser.parse_args()

    read_config(options.config_file)

    for option in dir(options):
        if isinstance(getattr(options, option), (six.string_types, bool)) and not option.startswith('_'):
            config[option] = getattr(options, option)

    if options.debug:
        config.console = True
        config.PROCESS_COUNT = 1
        config.SHOW_DEBUG = True

    if options.pcap_file:
        if options.pcap_file == '-':
            print("[i] using STDIN")
        else:
            for _ in options.pcap_file.split(','):
                if not os.path.isfile(_):
                    exit("[!] missing pcap file '%s'" % _)

            print("[i] using pcap file(s) '%s'" % options.pcap_file)

    if not config.DISABLE_CHECK_SUDO and not check_sudo():
        exit("[!] please run '%s' with sudo/Administrator privileges" % __file__)

    try:
        init()
        if config.profile:
            open(config.profile, "w+b").write("")
            cProfile.run("monitor()", config.profile)
        else:
            monitor()
    except KeyboardInterrupt:
        print("\r[x] stopping (Ctrl-C pressed)")


if __name__ == "__main__":
    show_final = True

    try:
        main()
    except SystemExit as ex:
        show_final = False

        if isinstance(get_ex_message(ex), six.string_types):
            print(get_ex_message(ex))
            os._exit(1)
    except IOError:
        show_final = False
        log_error(
            "\n\n[!] session abruptly terminated\n[?] (hint: \"https://stackoverflow.com/a/20997655\")")
    except Exception:
        msg = "\r[!] unhandled exception occurred ('%s')" % sys.exc_info()[1]
        msg += "\n[x] please report the following details at '':\n---\n'%s'\n---" % traceback.format_exc()
        log_error("\n\n%s" % msg.replace("\r", ""))

        print(msg)
    finally:
        if show_final:
            print("[i] finished")

        os._exit(0)
