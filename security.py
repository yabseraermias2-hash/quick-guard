import socket
import ssl
import requests
import concurrent.futures
import re 
from datetime import datetime, timezone

requests.packages.urllib3.disable_warnings()


def _hostname(target: str) -> str:
    return (
        target.replace("https://", "")
              .replace("http://", "")
              .split("/")[0]
              .split(":")[0]
    )


def _base_url(target: str) -> str:
    if target.startswith(("http://", "https://")):
        return target.rstrip("/")
    return f"https://{target}"


# ── Individual checks ──────────────────────────────────────────────────────────

def check_http_headers(target: str) -> dict:
    try:
        url = _base_url(target)
        resp = requests.get(url, timeout=10, allow_redirects=True, verify=False)
        h = resp.headers

        watched = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
            "Permissions-Policy",
        ]
        present = {k: h[k] for k in watched if k in h}
        missing = [k for k in watched if k not in h]

        return {
            "status_code": resp.status_code,
            "server": h.get("Server", "hidden"),
            "x_powered_by": h.get("X-Powered-By", "hidden"),
            "security_headers_present": present,
            "security_headers_missing": missing,
        }
    except Exception as e:
        return {"error": str(e)}


def check_ssl(target: str) -> dict:
    host = _hostname(target)
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
            s.settimeout(10)
            s.connect((host, 443))
            cert = s.getpeercert()

        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        days_remaining = (not_after - datetime.now(timezone.utc)).days

        return {
            "valid": True,
            "subject": dict(x[0] for x in cert["subject"]),
            "issuer": dict(x[0] for x in cert["issuer"]),
            "expires": cert["notAfter"],
            "days_remaining": days_remaining,
            "expired": days_remaining < 0,
        }
    except ssl.SSLCertVerificationError as e:
        return {"valid": False, "error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def check_open_ports(target: str) -> list:
    host = _hostname(target)
    port_map = {
        21: "FTP",
        22: "SSH",
        23: "Telnet",
        25: "SMTP",
        80: "HTTP",
        443: "HTTPS",
        8080: "HTTP-Alt",
        8443: "HTTPS-Alt",
        3306: "MySQL",
        5432: "PostgreSQL",
        6379: "Redis",
        27017: "MongoDB",
    }

    def probe(port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            if s.connect_ex((host, port)) == 0:
                s.close()
                return port
            s.close()
        except Exception:
            pass
        return None

    open_ports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        for port, result in zip(port_map.keys(), ex.map(probe, port_map.keys())):
            if result:
                open_ports.append({"port": port, "service": port_map[port]})

    return open_ports


def check_dns(target: str) -> dict:
    host = _hostname(target)
    results = {}

    # A records via stdlib
    try:
        infos = socket.getaddrinfo(host, None)
        results["A"] = list({info[4][0] for info in infos if info[0] == socket.AF_INET})
    except Exception:
        results["A"] = []

    # MX / NS / TXT via dnspython if available
    try:
        import dns.resolver  # type: ignore

        for rtype in ("MX", "NS", "TXT"):
            try:
                answers = dns.resolver.resolve(host, rtype)
                results[rtype] = [str(r) for r in answers]
            except Exception:
                results[rtype] = []
    except ImportError:
        results["note"] = "Install dnspython for MX/NS/TXT records"

    return results


def check_robots_sitemap(target: str) -> dict:
    base = _base_url(target)
    out = {}
    for path in ("/robots.txt", "/sitemap.xml"):
        try:
            r = requests.get(f"{base}{path}", timeout=8, verify=False)
            out[path] = {"status_code": r.status_code, "found": r.status_code == 200}
        except Exception:
            out[path] = {"status_code": None, "found": False}
    return out


# ── New scan modules ───────────────────────────────────────────────────────────

def check_technology(target: str) -> dict:
    """Detect CMS, frameworks, web server, and other technologies via headers,
    HTML content, meta tags, and common file-path probing."""
    result = {
        "server": None,
        "cms": [],
        "frameworks": [],
        "technologies": [],
    }
    try:
        url = _base_url(target)
        resp = requests.get(url, timeout=10, allow_redirects=True, verify=False)
        headers = resp.headers
        body = resp.text.lower() if resp.text else ""

        # ── Server / X-Powered-By ──────────────────────────────────────────
        result["server"] = headers.get("Server", None)
        powered = headers.get("X-Powered-By", "")
        generator = headers.get("X-Generator", "")

        if powered:
            result["technologies"].append(f"X-Powered-By: {powered}")
        if generator:
            result["technologies"].append(f"X-Generator: {generator}")

        # ── CMS detection via HTML & meta tags ─────────────────────────────
        cms_signatures = {
            "WordPress": [
                'wp-content', 'wp-includes', 'wordpress',
                'name="generator" content="wordpress',
            ],
            "Joomla": [
                '/media/jui/', 'joomla', 'name="generator" content="joomla',
            ],
            "Drupal": [
                'drupal.js', 'drupal.min.js', '/sites/default/',
                'name="generator" content="drupal',
            ],
            "Shopify": [
                'cdn.shopify.com', 'shopify.com', 'shopify',
            ],
        }
        for cms_name, sigs in cms_signatures.items():
            if any(sig in body for sig in sigs):
                if cms_name not in result["cms"]:
                    result["cms"].append(cms_name)
            # Also check generator header
            if cms_name.lower() in generator.lower():
                if cms_name not in result["cms"]:
                    result["cms"].append(cms_name)

        # ── Framework detection via HTML ───────────────────────────────────
        framework_signatures = {
            "React": ['react', 'data-reactroot', 'data-reactid', '_next/static'],
            "Angular": ['ng-version', 'ng-app', 'angular.js', 'angular.min.js'],
            "Vue": ['vue.js', 'vue.min.js', 'data-v-', '__vue'],
            "Laravel": ['laravel', 'csrf-token'],
            "Django": ['csrfmiddlewaretoken', 'django'],
            "Rails": ['csrf-param', 'data-turbolinks', 'turbo-frame',
                       'action_controller'],
        }
        for fw_name, sigs in framework_signatures.items():
            if any(sig in body for sig in sigs):
                if fw_name not in result["frameworks"]:
                    result["frameworks"].append(fw_name)

        # Also check X-Powered-By for framework hints
        powered_lower = powered.lower()
        for fw in ("Laravel", "Django", "Rails", "Express", "ASP.NET", "PHP"):
            if fw.lower() in powered_lower and fw not in result["frameworks"]:
                result["frameworks"].append(fw)

        # ── CMS path probing (lightweight HEAD requests) ───────────────────
        cms_paths = {
            "/wp-login.php": "WordPress",
            "/wp-admin/": "WordPress",
            "/administrator/": "Joomla",
            "/user/login": "Drupal",
        }

        def _probe_cms(path_cms):
            path, cms_name = path_cms
            try:
                r = requests.head(
                    f"{url}{path}", timeout=5, allow_redirects=True, verify=False
                )
                if r.status_code in (200, 301, 302, 403):
                    return cms_name
            except Exception:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for cms_hit in ex.map(_probe_cms, cms_paths.items()):
                if cms_hit and cms_hit not in result["cms"]:
                    result["cms"].append(cms_hit)

    except Exception as e:
        result["error"] = str(e)

    return result


def check_subdomains(target: str) -> list:
    """Enumerate subdomains via Certificate Transparency logs (crt.sh)."""
    host = _hostname(target)
    # Strip subdomains to get the registrable domain (simple heuristic)
    parts = host.split(".")
    if len(parts) > 2:
        domain = ".".join(parts[-2:])
    else:
        domain = host

    try:
        resp = requests.get(
            f"https://crt.sh/?q=%25.{domain}&output=json",
            timeout=12,
            verify=False,
        )
        if resp.status_code != 200:
            return [{"error": f"crt.sh returned status {resp.status_code}"}]

        data = resp.json()
        subdomains = set()
        for entry in data:
            name_value = entry.get("name_value", "")
            for name in name_value.split("\n"):
                name = name.strip().lower()
                if name and "*" not in name:
                    subdomains.add(name)

        return sorted(subdomains)[:50]
    except Exception as e:
        return [{"error": str(e)}]


def check_cookies(target: str) -> list:
    """Audit all Set-Cookie headers for Secure, HttpOnly, SameSite flags."""
    try:
        url = _base_url(target)
        resp = requests.get(url, timeout=10, allow_redirects=True, verify=False)

        raw_cookies = resp.headers.get("Set-Cookie", "")
        if not raw_cookies and not resp.cookies:
            return []

        results = []

        # Parse cookies from the response
        for cookie in resp.cookies:
            cookie_info = {
                "name": cookie.name,
                "secure": cookie.secure,
                "httponly": bool(cookie._rest.get("HttpOnly", cookie._rest.get("httponly", ""))),
                "samesite": None,
                "issues": [],
            }

            # Check SameSite from the cookie's attributes
            for key, val in cookie._rest.items():
                if key.lower() == "samesite":
                    cookie_info["samesite"] = val if val else None

            # Identify issues
            if not cookie_info["secure"]:
                cookie_info["issues"].append("Missing 'Secure' flag")
            if not cookie_info["httponly"]:
                cookie_info["issues"].append("Missing 'HttpOnly' flag")
            if not cookie_info["samesite"]:
                cookie_info["issues"].append("Missing 'SameSite' attribute")

            results.append(cookie_info)

        # Fallback: also parse raw Set-Cookie headers for extra coverage
        # Use resp.raw.headers.getlist if available (urllib3)
        try:
            raw_headers = resp.raw.headers.getlist("Set-Cookie")
        except Exception:
            raw_headers = []

        seen_names = {c["name"] for c in results}
        for raw in raw_headers:
            parts = raw.split(";")
            if not parts:
                continue
            name_val = parts[0].strip()
            if "=" not in name_val:
                continue
            name = name_val.split("=", 1)[0].strip()
            if name in seen_names:
                continue
            seen_names.add(name)

            attrs_lower = [p.strip().lower() for p in parts[1:]]
            secure = any("secure" == a for a in attrs_lower)
            httponly = any("httponly" == a for a in attrs_lower)
            samesite = None
            for a in attrs_lower:
                if a.startswith("samesite="):
                    samesite = a.split("=", 1)[1].strip()

            issues = []
            if not secure:
                issues.append("Missing 'Secure' flag")
            if not httponly:
                issues.append("Missing 'HttpOnly' flag")
            if not samesite:
                issues.append("Missing 'SameSite' attribute")

            results.append({
                "name": name,
                "secure": secure,
                "httponly": httponly,
                "samesite": samesite,
                "issues": issues,
            })

        return results
    except Exception as e:
        return [{"error": str(e)}]


def check_sensitive_paths(target: str) -> list:
    """Probe common sensitive / informational paths with HEAD requests."""
    url = _base_url(target)

    paths = [
        "/.env",
        "/.git/HEAD",
        "/.git/config",
        "/wp-admin/",
        "/admin/",
        "/administrator/",
        "/backup.zip",
        "/backup.sql",
        "/.htaccess",
        "/server-status",
        "/phpinfo.php",
        "/.well-known/security.txt",
        "/robots.txt",
        "/sitemap.xml",
        "/crossdomain.xml",
        "/.DS_Store",
        "/web.config",
    ]

    # Paths where 403 also counts as "exposed" (the file exists but is restricted)
    sensitive_403 = {
        "/.env", "/.git/HEAD", "/.git/config", "/.htaccess",
        "/backup.zip", "/backup.sql", "/.DS_Store", "/web.config",
        "/server-status", "/phpinfo.php",
    }

    def _probe(path):
        try:
            r = requests.head(
                f"{url}{path}", timeout=6, allow_redirects=False, verify=False
            )
            exposed = r.status_code == 200 or (
                r.status_code == 403 and path in sensitive_403
            )
            return {"path": path, "status": r.status_code, "exposed": exposed}
        except Exception:
            return {"path": path, "status": None, "exposed": False}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_probe, paths))

    return results


def _dns_query_doh(name: str, rtype: str = "TXT") -> list:
    """Query Cloudflare DNS-over-HTTPS for a given record type."""
    try:
        resp = requests.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": name, "type": rtype},
            headers={"Accept": "application/dns-json"},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        answers = data.get("Answer", [])
        return [a.get("data", "").strip('"') for a in answers if a.get("data")]
    except Exception:
        return []


def check_email_security(target: str) -> dict:
    """Check SPF, DKIM, and DMARC DNS records for the domain."""
    host = _hostname(target)
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) > 2 else host

    result = {"spf": None, "dkim": None, "dmarc": None, "issues": []}

    # ── Try dnspython first, fall back to DoH ──────────────────────────────
    def _resolve_txt(name):
        try:
            import dns.resolver  # type: ignore
            answers = dns.resolver.resolve(name, "TXT")
            return [str(r).strip('"') for r in answers]
        except ImportError:
            return _dns_query_doh(name, "TXT")
        except Exception:
            return _dns_query_doh(name, "TXT")

    # SPF
    try:
        txt_records = _resolve_txt(domain)
        for rec in txt_records:
            if "v=spf1" in rec:
                result["spf"] = rec
                break
    except Exception:
        pass
    if not result["spf"]:
        result["issues"].append("No SPF record found — email spoofing risk")

    # DKIM (try common selector "default")
    try:
        dkim_records = _resolve_txt(f"default._domainkey.{domain}")
        for rec in dkim_records:
            if rec:
                result["dkim"] = rec
                break
    except Exception:
        pass
    if not result["dkim"]:
        result["issues"].append(
            "No DKIM record found for selector 'default' "
            "(other selectors may exist)"
        )

    # DMARC
    try:
        dmarc_records = _resolve_txt(f"_dmarc.{domain}")
        for rec in dmarc_records:
            if "v=DMARC1" in rec.upper():
                result["dmarc"] = rec
                break
    except Exception:
        pass
    if not result["dmarc"]:
        result["issues"].append("No DMARC record found — email spoofing risk")

    return result


def check_whois(target: str) -> dict:
    """Retrieve WHOIS-like data via RDAP (Registration Data Access Protocol)."""
    host = _hostname(target)
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) > 2 else host

    result = {
        "domain": domain,
        "registrar": None,
        "registration_date": None,
        "expiration_date": None,
        "status": [],
    }

    try:
        resp = requests.get(f"https://rdap.org/domain/{domain}", timeout=10)
        if resp.status_code != 200:
            result["error"] = f"RDAP returned status {resp.status_code}"
            return result

        data = resp.json()

        # Registrar (from entities with "registrar" role)
        for entity in data.get("entities", []):
            roles = entity.get("roles", [])
            if "registrar" in roles:
                vcard = entity.get("vcardArray", [None, []])
                if len(vcard) > 1:
                    for field in vcard[1]:
                        if field[0] == "fn":
                            result["registrar"] = field[3]
                            break
                # Fallback to handle field
                if not result["registrar"]:
                    result["registrar"] = entity.get("handle")

        # Events (registration, expiration)
        for event in data.get("events", []):
            action = event.get("eventAction", "")
            date = event.get("eventDate", "")
            if action == "registration":
                result["registration_date"] = date
            elif action == "expiration":
                result["expiration_date"] = date

        # Status
        result["status"] = data.get("status", [])

    except Exception as e:
        result["error"] = str(e)

    return result

# ── Automated Exploitation ──────────────────────────────────────────────────────

def check_nmap_vuln(target: str) -> dict:
    """Run nmap -sV --script vuln to actively discover and exploit vulnerabilities."""
    import subprocess
    host = _hostname(target)
    try:
        # Limit to top 100 ports for speed, run vulnerability scripts
        res = subprocess.run(['nmap', '-sV', '--top-ports', '100', '--script', 'vuln', host], 
                             capture_output=True, text=True, timeout=60)
        output = res.stdout
        
        # Look for CVE references
        cves = re.findall(r'CVE-\d{4}-\d{4,7}', output)
        vulnerable = "VULNERABLE" in output or len(cves) > 0
        
        return {
            "vulnerable": vulnerable,
            "cves_found": list(set(cves)),
            "raw_output": output[:3000] # truncate to avoid blowing up memory
        }
    except Exception as e:
        return {"error": f"Nmap failed: {e}. Is nmap installed?"}


# ── Full scan ──────────────────────────────────────────────────────────────────

def full_scan(target: str, progress_cb=None) -> dict:
    def _p(step: str, status: str = "running"):
        if progress_cb:
            progress_cb({"type": "scan_step", "step": step, "status": status})

    host = _hostname(target)
    report = {"target": host, "timestamp": datetime.now(timezone.utc).isoformat()}

    _p("Checking HTTP headers")
    report["headers"] = check_http_headers(target)
    _p("Checking HTTP headers", "done")

    _p("Checking SSL certificate")
    report["ssl"] = check_ssl(host)
    _p("Checking SSL certificate", "done")

    _p("Scanning open ports")
    report["open_ports"] = check_open_ports(host)
    _p("Scanning open ports", "done")

    _p("DNS lookup")
    report["dns"] = check_dns(host)
    _p("DNS lookup", "done")

    _p("Checking robots.txt and sitemap")
    report["robots_sitemap"] = check_robots_sitemap(target)
    _p("Checking robots.txt and sitemap", "done")

    # ── New modules ────────────────────────────────────────────────────────

    _p("Fingerprinting technologies")
    report["technology"] = check_technology(target)
    _p("Fingerprinting technologies", "done")

    _p("Enumerating subdomains")
    report["subdomains"] = check_subdomains(target)
    _p("Enumerating subdomains", "done")

    _p("Auditing cookies")
    report["cookies"] = check_cookies(target)
    _p("Auditing cookies", "done")

    _p("Probing sensitive paths")
    report["sensitive_paths"] = check_sensitive_paths(target)
    _p("Probing sensitive paths", "done")

    _p("Checking email security")
    report["email_security"] = check_email_security(target)
    _p("Checking email security", "done")

    _p("WHOIS / RDAP lookup")
    report["whois"] = check_whois(target)
    _p("WHOIS / RDAP lookup", "done")
    
    _p("Running Nmap Vulnerability Scripts")
    report["nmap_vuln"] = check_nmap_vuln(target)
    _p("Running Nmap Vulnerability Scripts", "done")

    # ── Risk summary ──────────────────────────────────────────────────────
    risks = []

    # Existing risk checks
    missing_headers = report["headers"].get("security_headers_missing", [])
    if missing_headers:
        risks.append(f"Missing security headers: {', '.join(missing_headers)}")
    ssl_info = report["ssl"]
    if ssl_info.get("expired"):
        risks.append("SSL certificate is EXPIRED")
    elif 0 <= ssl_info.get("days_remaining", 999) < 30:
        risks.append(f"SSL certificate expires in {ssl_info['days_remaining']} days")
    if not ssl_info.get("valid") and "error" in ssl_info:
        risks.append(f"SSL issue: {ssl_info['error']}")
    dangerous = [p for p in report["open_ports"] if p["port"] in (21, 23, 3306, 5432, 6379, 27017)]
    if dangerous:
        risks.append(f"Exposed sensitive ports: {[p['port'] for p in dangerous]}")

    # New risk: exposed sensitive paths (Critical)
    critical_paths = {"/.env", "/.git/HEAD", "/.git/config"}
    exposed = [
        p for p in report.get("sensitive_paths", [])
        if isinstance(p, dict) and p.get("exposed")
    ]
    critical_exposed = [p for p in exposed if p["path"] in critical_paths]
    other_exposed = [p for p in exposed if p["path"] not in critical_paths
                     and p["path"] not in ("/robots.txt", "/sitemap.xml")]
    if critical_exposed:
        paths_str = ", ".join(p["path"] for p in critical_exposed)
        risks.append(f"CRITICAL EXPOSURE: {paths_str}")
        
    nmap_info = report.get("nmap_vuln", {})
    if nmap_info.get("vulnerable"):
        cves = ", ".join(nmap_info.get("cves_found", []))
        risks.append(f"CRITICAL VULNERABILITIES FOUND VIA NMAP: {cves}")
        risks.append(f"[CRITICAL] Exposed sensitive files: {paths_str}")
    if other_exposed:
        paths_str = ", ".join(p["path"] for p in other_exposed)
        risks.append(f"Exposed paths: {paths_str}")

    # New risk: missing email security (Medium)
    email_sec = report.get("email_security", {})
    if not email_sec.get("spf") or not email_sec.get("dmarc"):
        missing_email = []
        if not email_sec.get("spf"):
            missing_email.append("SPF")
        if not email_sec.get("dmarc"):
            missing_email.append("DMARC")
        risks.append(
            f"[MEDIUM] Missing email security records: {', '.join(missing_email)}"
        )

    # New risk: insecure cookies (Medium)
    insecure_cookies = [
        c for c in report.get("cookies", [])
        if isinstance(c, dict) and c.get("issues")
    ]
    if insecure_cookies:
        names = ", ".join(c.get("name", "?") for c in insecure_cookies[:5])
        risks.append(f"[MEDIUM] Insecure cookies: {names}")

    report["risk_summary"] = risks if risks else ["No critical issues detected"]

    if progress_cb:
        progress_cb({"type": "scan_complete", "report": report})

    return report
