"""Sign-up email checks (rescrub/emails.py). DNS is replaced by a fake resolver."""

import dns.resolver
import pytest

from rescrub import emails


@pytest.mark.parametrize("email", [
    "jordan.lee@gmail.com", "jordanlee+rescrub@gmail.com", "j.o.r.d.a.n@googlemail.com",
    "jordan_lee-2@outlook.com", "j.lee@hotmail.co.uk",
    "jordan_lee@yahoo.com", "jordan.lee@yahoo.com", "jordan-rescrub@ymail.com",
    "jordan.lee@icloud.com", "jordan-lee+x@proton.me", "jordanlee@aol.com",
    "first.last@school.edu", "o'brien@hospital.org", "a@xn--bcher-kva.example",
])
def test_ordinary_addresses_pass(email):
    assert emails.email_problem(email, check_dns=False) is None


@pytest.mark.parametrize("email, says", [
    ("plainaddress", "valid"), ("two@@gmail.com", "valid"), ("a..b@school.edu", "valid"),
    (".a@school.edu", "valid"), ("a@school", "valid"), ("a@-school.edu", "valid"), ("a@school.c0m", "valid"),
    ("ab12@gmail.com", "Gmail"), ("jordan_lee@gmail.com", "Gmail"), ("jordan..lee@gmail.com", "valid"),
    (".jordanlee@gmail.com", "valid"), ("a" * 31 + "@gmail.com", "Gmail"), ("jordanlee+@gmail.com", "+"),
    ("1jordan@outlook.com", "Outlook"), ("jordan.@hotmail.com", "valid"),
    ("jor@yahoo.com", "Yahoo"), ("jor.dan.lee@yahoo.com", "Yahoo"), ("jordan_@yahoo.com", "Yahoo"),
    ("jordan+x@yahoo.com", "+"), ("jo@icloud.com", "iCloud"), ("9lives@me.com", "iCloud"),
    ("jordan+x@aol.com", "+"),
])
def test_bad_addresses_are_explained(email, says):
    problem = emails.email_problem(email, check_dns=False)
    assert problem and says in problem, (email, problem)


class FakeResolver:
    """Answers from a table: {(domain, type): records | exception class}."""
    table: dict = {}

    def __init__(self):
        self.lifetime = None

    def resolve(self, name, rtype):
        answer = self.table.get((name, rtype), dns.resolver.NoAnswer)
        if isinstance(answer, type) and issubclass(answer, Exception):
            raise answer()
        return answer


class MX:
    def __init__(self, exchange):
        self.exchange = exchange


@pytest.fixture
def fake_dns(monkeypatch):
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)
    FakeResolver.table = {
        ("school.edu", "MX"): [MX("mx.school.edu.")],
        ("nomx.org", "A"): ["192.0.2.1"],
        ("nullmx.org", "MX"): [MX(".")],
        ("typo-domain.cmo", "MX"): dns.resolver.NXDOMAIN,
        ("parked.net", "MX"): dns.resolver.NoAnswer,
        ("slow.org", "MX"): dns.resolver.LifetimeTimeout,
    }
    return FakeResolver.table


def test_domains_must_receive_mail(fake_dns):
    assert emails.email_problem("a.person@school.edu") is None
    assert emails.email_problem("a.person@nomx.org") is None          # no MX, but has an address
    assert emails.email_problem("a.person@slow.org") is None          # DNS trouble doesn't block sign-up
    for domain in ("nullmx.org", "typo-domain.cmo", "parked.net"):
        problem = emails.email_problem(f"a.person@{domain}")
        assert problem and domain in problem


def test_known_providers_skip_dns(fake_dns):
    fake_dns[("gmail.com", "MX")] = dns.resolver.NXDOMAIN  # would fail if it were looked up
    assert emails.email_problem("jordan.lee@gmail.com") is None
