"""Is this a real-looking email address? Used by sign-up (POST /auth/register).

1. Syntax: an ordinary address (RFC 5321 "dot-atom" name, DNS domain, letters-only top-level domain).
2. Well-known providers: the provider's own rules for the name before the @ (e.g. Gmail names are
   6-30 letters, numbers and periods). A "+tag" is allowed where the provider supports it.
3. Any other domain: DNS must show it receives mail (an MX record, or an A/AAAA record, which mail
   servers also accept). Lookup failures other than "no such domain" don't block sign-up.

There is no email service, so this can't prove the person owns the mailbox; it stops typos and
made-up domains.
"""

import re
from dataclasses import dataclass

LOCAL_RE = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
TLD_RE = re.compile(r"^([a-z]{2,63}|xn--[a-z0-9-]{1,59})$")


@dataclass(frozen=True)
class Provider:
    name: str
    domains: tuple[str, ...]
    pattern: re.Pattern  # the name before the @, without any +tag
    rule: str  # shown to the person when the name doesn't fit
    plus_tags: bool = True


PROVIDERS = (
    Provider("Gmail", ("gmail.com", "googlemail.com"),
             re.compile(r"^(?=(?:[a-z0-9]\.?){6,30}$)[a-z0-9](?:\.?[a-z0-9])*$"),
             "Gmail addresses have 6–30 letters, numbers and periods before the @."),
    Provider("Outlook", ("outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk", "outlook.co.uk",
                         "live.co.uk", "hotmail.fr", "outlook.fr", "live.fr", "hotmail.de", "outlook.de",
                         "hotmail.it", "outlook.it", "hotmail.es", "outlook.es", "live.ca", "hotmail.ca"),
             re.compile(r"^[a-z](?:[a-z0-9_-]|\.(?=[a-z0-9_-])){0,63}$"),
             "Outlook addresses start with a letter and use letters, numbers, periods, hyphens and underscores."),
    Provider("Yahoo", ("yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.ca", "yahoo.fr",
                       "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.co.in", "yahoo.com.au", "yahoo.co.jp"),
             re.compile(r"^(?=[^.]*\.?[^.]*$)[a-z][a-z0-9_.]{2,30}[a-z0-9](?:-[a-z0-9]+)?$"),
             "Yahoo addresses have 4–32 letters, numbers, underscores and at most one period, starting with a letter.",
             plus_tags=False),
    Provider("iCloud", ("icloud.com", "me.com", "mac.com"),
             re.compile(r"^[a-z](?:[a-z0-9_]|\.(?=[a-z0-9_])){2,19}$"),
             "iCloud addresses have 3–20 letters, numbers, periods and underscores, starting with a letter."),
    Provider("Proton", ("proton.me", "protonmail.com", "protonmail.ch", "pm.me"),
             re.compile(r"^[a-z0-9](?:[a-z0-9_-]|\.(?=[a-z0-9_-])){0,39}$"),
             "Proton addresses have up to 40 letters, numbers, periods, hyphens and underscores."),
    Provider("AOL", ("aol.com", "aim.com"),
             re.compile(r"^[a-z](?:[a-z0-9_]|\.(?=[a-z0-9_])){2,31}$"),
             "AOL addresses have 3–32 letters, numbers, periods and underscores, starting with a letter.",
             plus_tags=False),
)
BY_DOMAIN = {d: p for p in PROVIDERS for d in p.domains}


def syntax_problem(email: str) -> str | None:
    """Why `email` (already lower-cased and trimmed) isn't an ordinary address, or None."""
    if len(email) > 254 or email.count("@") != 1:
        return "That is not a valid email address."
    local, domain = email.split("@")
    labels = domain.split(".")
    if (not 1 <= len(local) <= 64 or not LOCAL_RE.match(local) or len(labels) < 2
            or not all(LABEL_RE.match(label) for label in labels) or not TLD_RE.match(labels[-1])):
        return "That is not a valid email address."
    return None


def provider_problem(email: str) -> str | None:
    """Why the name doesn't fit the provider's rules (for well-known providers), or None."""
    local, domain = email.split("@")
    provider = BY_DOMAIN.get(domain)
    if provider is None:
        return None
    name, plus, tag = local.partition("+")
    if plus and (not provider.plus_tags or not tag):
        return f"{provider.name} addresses can't contain a “+”."
    return None if provider.pattern.match(name) else provider.rule


def receives_mail(domain: str, timeout: float = 3.0) -> bool:
    """False only if DNS says the domain doesn't exist or can't receive mail."""
    import dns.exception
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    try:
        mx = resolver.resolve(domain, "MX")
        # A "null MX" (RFC 7505: one record, exchange ".") means the domain accepts no mail.
        return not all(str(r.exchange) == "." for r in mx)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass  # no MX: mail servers fall back to the domain's own address
    except dns.exception.DNSException:
        return True  # resolver trouble is not the person's fault
    for rtype in ("A", "AAAA"):
        try:
            resolver.resolve(domain, rtype)
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except dns.exception.DNSException:
            return True
    return False


def email_problem(email: str, check_dns: bool = True) -> str | None:
    """A message for the person if `email` can't be used to sign up, else None."""
    if problem := syntax_problem(email) or provider_problem(email):
        return problem
    domain = email.split("@")[1]
    if check_dns and domain not in BY_DOMAIN and not receives_mail(domain):
        return f"“{domain}” doesn't receive email. Check the part after the @."
    return None
